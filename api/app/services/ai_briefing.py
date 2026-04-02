import json
import logging
import os
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import yfinance as yf
from sqlalchemy.orm import Session

from .market_data import get_symbol_data

GROQ_CHAT_COMPLETIONS_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODELS_URL = "https://api.groq.com/openai/v1/models"
logger = logging.getLogger("stock_data.ai_briefing")
logger.setLevel(logging.INFO)


class BriefingError(Exception):
    def __init__(self, message: str, status_code: int = 500) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _extract_headlines(news_items: list[dict], lookback_days: int, limit: int = 5) -> list[str]:
    now_utc = datetime.now(timezone.utc)
    cutoff = now_utc - timedelta(days=max(7, min(365, lookback_days)))
    headlines: list[str] = []
    for item in news_items:
        content = item.get("content") if isinstance(item.get("content"), dict) else item
        title = str(content.get("title", "")).strip()
        if not title:
            continue

        published_at: datetime | None = None
        raw_pub_date = str(content.get("pubDate", "")).strip()
        if raw_pub_date:
            try:
                published_at = datetime.fromisoformat(raw_pub_date.replace("Z", "+00:00"))
            except ValueError:
                published_at = None

        if published_at is None:
            raw_epoch = content.get("providerPublishTime", item.get("providerPublishTime"))
            if raw_epoch is not None:
                try:
                    published_at = datetime.fromtimestamp(int(raw_epoch), tz=timezone.utc)
                except (TypeError, ValueError, OSError):
                    published_at = None

        if published_at and published_at < cutoff:
            continue
        if not title or title in headlines:
            continue
        headlines.append(title)
        if len(headlines) >= limit:
            break
    return headlines


def _build_prompt(symbol: str, company_name: str, rows: list, headlines: list[str], days: int) -> str:
    latest = rows[-1]
    previous = rows[-2] if len(rows) > 1 else None
    first = rows[0]
    day_change_pct = 0.0
    if previous and previous.close:
        day_change_pct = ((latest.close - previous.close) / previous.close) * 100

    period_change_pct = 0.0
    if first and first.close:
        period_change_pct = ((latest.close - first.close) / first.close) * 100

    highs = [float(r.high) for r in rows]
    lows = [float(r.low) for r in rows]
    volumes = [int(r.volume) for r in rows]

    headlines_block = "\n".join(f"- {h}" for h in headlines) if headlines else "- No recent headlines available"

    return (
        "You are a concise market analyst. Write exactly 2 sentences, no markdown, no bullets. "
        "Explain the latest session movement and relate it to recent news sentiment if available.\n\n"
        f"Symbol: {symbol}\n"
        f"Company: {company_name}\n"
        f"Latest date: {latest.date}\n"
        f"Open: {latest.open:.2f}\n"
        f"Close: {latest.close:.2f}\n"
        f"High: {latest.high:.2f}\n"
        f"Low: {latest.low:.2f}\n"
        f"Volume: {latest.volume}\n"
        f"Daily return: {day_change_pct:.2f}%\n"
        f"Window requested: {days} days\n"
        f"Window covered points: {len(rows)}\n"
        f"Window return: {period_change_pct:.2f}%\n"
        f"Window high: {max(highs):.2f}\n"
        f"Window low: {min(lows):.2f}\n"
        f"Average volume in window: {int(sum(volumes) / len(volumes))}\n"
        f"Moving average 7d: {(latest.moving_avg_7 if latest.moving_avg_7 is not None else latest.close):.2f}\n"
        f"Volatility 20d: {(latest.volatility_20d if latest.volatility_20d is not None else 0.0):.4f}\n"
        "Recent headlines:\n"
        f"{headlines_block}\n"
    )


def _parse_error_message(raw_error: str) -> str:
    if not raw_error:
        return ""

    try:
        parsed_error = json.loads(raw_error)
        return str(parsed_error.get("error", {}).get("message", "")).strip()
    except json.JSONDecodeError:
        return raw_error.strip()


def _probe_groq_models(api_key: str, timeout_seconds: int = 12) -> tuple[int, str, list[str]]:
    req = Request(
        url=GROQ_MODELS_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="GET",
    )

    try:
        with urlopen(req, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8", errors="replace")
            status_code = getattr(response, "status", 200)
    except HTTPError as exc:
        raw_error = exc.read().decode("utf-8", errors="replace")
        message = _parse_error_message(raw_error) or "No response body from /models endpoint"
        return exc.code, message, []
    except URLError as exc:
        return 0, f"Could not reach /models endpoint: {exc.reason}", []

    try:
        parsed = json.loads(raw)
        model_ids = [item.get("id", "") for item in parsed.get("data", []) if isinstance(item, dict)]
        model_ids = [str(model_id).strip() for model_id in model_ids if str(model_id).strip()]
    except json.JSONDecodeError:
        return status_code, "Could not parse /models response JSON", []

    return status_code, "ok", model_ids


def _call_groq(prompt: str) -> tuple[str, str]:
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        raise BriefingError(
            "GROQ_API_KEY is missing. Add GROQ_API_KEY in backend .env and restart FastAPI.",
            status_code=500,
        )

    model = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant").strip() or "llama-3.1-8b-instant"
    payload = {
        "model": model,
        "temperature": 0.2,
        "max_tokens": 180,
        "messages": [
            {
                "role": "system",
                "content": "You generate short factual stock briefings from numeric context and headlines.",
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
    }

    req = Request(
        url=GROQ_CHAT_COMPLETIONS_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "stock-data-briefing/1.0",
        },
        method="POST",
    )

    try:
        with urlopen(req, timeout=25) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        raw_error = exc.read().decode("utf-8", errors="replace")
        response_message = _parse_error_message(raw_error)
        request_id = exc.headers.get("x-request-id", "") if exc.headers else ""

        if exc.code in (401, 403):
            probe_status, probe_message, available_models = _probe_groq_models(api_key)
            sample_models = ", ".join(available_models[:6]) if available_models else "none"

            if probe_status == 200 and available_models:
                if model not in available_models:
                    raise BriefingError(
                        f"Groq rejected model access for '{model}'. API key is valid, but this model is not available for your account. "
                        f"Set GROQ_MODEL to one of: {sample_models}.",
                        status_code=502,
                    ) from exc

                raise BriefingError(
                    f"Groq returned {exc.code} for chat completions even though /models is accessible. "
                    f"Model '{model}' appears visible. Check project/org restrictions and usage limits. "
                    f"Request ID: {request_id or 'n/a'}.",
                    status_code=502,
                ) from exc

            if probe_status in (401, 403):
                raise BriefingError(
                    f"Groq authentication failed. API key is present but was rejected by /models ({probe_status}). "
                    "Regenerate GROQ_API_KEY, ensure correct project scope, then restart FastAPI.",
                    status_code=502,
                ) from exc

            detail = response_message or probe_message or "No response body from Groq"
            raise BriefingError(
                f"Groq returned {exc.code}. Additional diagnostics: {detail}. Request ID: {request_id or 'n/a'}.",
                status_code=502,
            ) from exc

        message = response_message or "No response body from Groq"
        raise BriefingError(
            f"Groq API request failed ({exc.code}): {message}. Request ID: {request_id or 'n/a'}.",
            status_code=502,
        ) from exc
    except URLError as exc:
        raise BriefingError(
            f"Could not reach Groq API: {exc.reason}. Check network egress and DNS from runtime.",
            status_code=502,
        ) from exc

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BriefingError(
            "Groq API returned invalid JSON. Retry request and check Groq service status.",
            status_code=502,
        ) from exc

    summary = (
        parsed.get("choices", [{}])[0]
        .get("message", {})
        .get("content", "")
        .strip()
    )
    if not summary:
        raise BriefingError(
            "Groq API returned an empty completion. Verify model availability and account limits.",
            status_code=502,
        )

    return summary, model


def build_daily_briefing(db: Session, symbol: str, days: int) -> dict | None:
    company, rows = get_symbol_data(db, symbol, days)
    if company is None:
        return None
    if not rows:
        raise BriefingError(
            "No market data found. Run POST /api/refresh before requesting AI briefing.",
            status_code=404,
        )

    headlines: list[str] = []
    news_pool: list[dict] = []
    seen_news_ids: set[str] = set()
    ticker_candidates = [
        company.ticker,
        company.symbol,
        company.ticker.split(".")[0],
    ]

    for candidate in ticker_candidates:
        candidate = str(candidate).strip()
        if not candidate:
            continue
        try:
            news_items = yf.Ticker(candidate).news or []
        except Exception:
            news_items = []

        if not isinstance(news_items, list):
            continue

        for item in news_items:
            if not isinstance(item, dict):
                continue
            item_id = str(item.get("id", "")).strip() or str(item.get("uuid", "")).strip()
            if item_id and item_id in seen_news_ids:
                continue
            if item_id:
                seen_news_ids.add(item_id)
            news_pool.append(item)

    lookback_days = max(7, min(365, days))
    headlines = _extract_headlines(news_pool, lookback_days=lookback_days)

    prompt = _build_prompt(company.symbol, company.name, rows, headlines, days)
    summary, model = _call_groq(prompt)

    logger.info(
        "briefing_generated symbol=%s model=%s headlines_used=%s lookback_days=%s points=%s",
        company.symbol,
        model,
        len(headlines),
        lookback_days,
        len(rows),
    )

    return {
        "symbol": company.symbol,
        "summary": summary,
        "model": model,
        "headlines_used": len(headlines),
        "headlines_lookback_days": lookback_days,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }