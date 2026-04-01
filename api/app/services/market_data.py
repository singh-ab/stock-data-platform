from datetime import timedelta

import numpy as np
import pandas as pd
import yfinance as yf
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from ..models import Company, StockPrice

TRACKED_COMPANIES = {
    "INFY": {"name": "Infosys", "exchange": "NSE", "ticker": "INFY.NS"},
    "TCS": {"name": "Tata Consultancy Services", "exchange": "NSE", "ticker": "TCS.NS"},
    "RELIANCE": {"name": "Reliance Industries", "exchange": "NSE", "ticker": "RELIANCE.NS"},
    "AAPL": {"name": "Apple", "exchange": "NASDAQ", "ticker": "AAPL"},
    "MSFT": {"name": "Microsoft", "exchange": "NASDAQ", "ticker": "MSFT"},
}


def _safe_float(value) -> float | None:
    if pd.isna(value):
        return None
    return float(value)


def _prepare_dataframe(raw_df: pd.DataFrame) -> pd.DataFrame:
    df = raw_df.copy().reset_index()
    df = df.rename(
        columns={
            "Date": "date",
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Adj Close": "adj_close",
            "Volume": "volume",
        }
    )

    required = ["date", "open", "high", "low", "close", "adj_close", "volume"]
    df = df[required]
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    df = df.dropna(subset=["date", "open", "close"])

    df["daily_return"] = ((df["close"] - df["open"]) / df["open"]).replace([np.inf, -np.inf], np.nan)
    df["moving_avg_7"] = df["close"].rolling(window=7, min_periods=1).mean()
    df["week52_high"] = df["close"].rolling(window=252, min_periods=1).max()
    df["week52_low"] = df["close"].rolling(window=252, min_periods=1).min()
    df["volatility_20d"] = df["daily_return"].rolling(window=20, min_periods=2).std()

    return df


def _upsert_company(db: Session, symbol: str, meta: dict) -> Company:
    company = db.scalar(select(Company).where(Company.symbol == symbol))
    if company:
        company.name = meta["name"]
        company.exchange = meta["exchange"]
        company.ticker = meta["ticker"]
        db.flush()
        return company

    company = Company(symbol=symbol, name=meta["name"], exchange=meta["exchange"], ticker=meta["ticker"])
    db.add(company)
    db.flush()
    return company


def _upsert_prices(db: Session, company_id: int, df: pd.DataFrame) -> int:
    count = 0
    for _, row in df.iterrows():
        stmt = insert(StockPrice).values(
            company_id=company_id,
            date=row["date"],
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            adj_close=float(row["adj_close"]),
            volume=int(row["volume"]),
            daily_return=_safe_float(row["daily_return"]),
            moving_avg_7=_safe_float(row["moving_avg_7"]),
            week52_high=_safe_float(row["week52_high"]),
            week52_low=_safe_float(row["week52_low"]),
            volatility_20d=_safe_float(row["volatility_20d"]),
        )
        db.execute(
            stmt.on_conflict_do_update(
                constraint="uq_company_date",
                set_={
                    "open": stmt.excluded.open,
                    "high": stmt.excluded.high,
                    "low": stmt.excluded.low,
                    "close": stmt.excluded.close,
                    "adj_close": stmt.excluded.adj_close,
                    "volume": stmt.excluded.volume,
                    "daily_return": stmt.excluded.daily_return,
                    "moving_avg_7": stmt.excluded.moving_avg_7,
                    "week52_high": stmt.excluded.week52_high,
                    "week52_low": stmt.excluded.week52_low,
                    "volatility_20d": stmt.excluded.volatility_20d,
                },
            )
        )
        count += 1
    return count


def refresh_market_data(db: Session) -> dict[str, int]:
    rows = {}
    for symbol, meta in TRACKED_COMPANIES.items():
        raw = yf.Ticker(meta["ticker"]).history(period="2y", interval="1d", auto_adjust=False)
        if raw.empty:
            rows[symbol] = 0
            continue

        company = _upsert_company(db, symbol, meta)
        prepared = _prepare_dataframe(raw)
        rows[symbol] = _upsert_prices(db, company.id, prepared)

    db.commit()
    return rows


def get_companies(db: Session):
    items = db.scalars(select(Company).order_by(Company.symbol)).all()
    return [{"symbol": i.symbol, "name": i.name, "exchange": i.exchange} for i in items]


def get_symbol_data(db: Session, symbol: str, days: int):
    company = db.scalar(select(Company).where(Company.symbol == symbol.upper()))
    if not company:
        return None, []

    latest = db.scalar(select(func.max(StockPrice.date)).where(StockPrice.company_id == company.id))
    if latest is None:
        return company, []

    start = latest - timedelta(days=days - 1)
    rows = db.scalars(
        select(StockPrice)
        .where(StockPrice.company_id == company.id)
        .where(StockPrice.date >= start)
        .order_by(StockPrice.date.asc())
    ).all()
    return company, list(rows)


def build_summary(db: Session, symbol: str):
    company = db.scalar(select(Company).where(Company.symbol == symbol.upper()))
    if not company:
        return None

    latest = db.scalar(select(func.max(StockPrice.date)).where(StockPrice.company_id == company.id))
    if latest is None:
        return None

    start = latest - timedelta(days=364)
    closes = db.execute(
        select(StockPrice.close)
        .where(StockPrice.company_id == company.id)
        .where(StockPrice.date >= start)
    ).scalars().all()

    if not closes:
        return None

    latest_close = db.scalar(
        select(StockPrice.close)
        .where(StockPrice.company_id == company.id)
        .where(StockPrice.date == latest)
    )

    return {
        "symbol": company.symbol,
        "days_covered": len(closes),
        "latest_close": float(latest_close),
        "average_close": float(np.mean(closes)),
        "week52_high": float(np.max(closes)),
        "week52_low": float(np.min(closes)),
    }


def build_comparison(db: Session, symbol1: str, symbol2: str, days: int):
    c1, rows1 = get_symbol_data(db, symbol1, days)
    c2, rows2 = get_symbol_data(db, symbol2, days)
    if c1 is None or c2 is None or not rows1 or not rows2:
        return None

    by_date_1 = {r.date: r for r in rows1}
    by_date_2 = {r.date: r for r in rows2}
    dates = sorted(set(by_date_1.keys()) & set(by_date_2.keys()))
    if not dates:
        return None

    base1 = by_date_1[dates[0]].close
    base2 = by_date_2[dates[0]].close
    points = []
    for d in dates:
        v1 = by_date_1[d].close
        v2 = by_date_2[d].close
        points.append(
            {
                "date": d,
                "symbol1_close": float(v1),
                "symbol2_close": float(v2),
                "symbol1_return_pct": float(((v1 - base1) / base1) * 100),
                "symbol2_return_pct": float(((v2 - base2) / base2) * 100),
            }
        )

    return {"symbol1": symbol1.upper(), "symbol2": symbol2.upper(), "points": points}
