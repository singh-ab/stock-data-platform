"use client";

import { useEffect, useMemo, useState } from "react";

type Company = {
  symbol: string;
  name: string;
  exchange: string;
};

type StockPoint = {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  daily_return: number | null;
  moving_avg_7: number | null;
  week52_high: number | null;
  week52_low: number | null;
  volatility_20d: number | null;
};

type Summary = {
  symbol: string;
  days_covered: number;
  latest_close: number;
  average_close: number;
  week52_high: number;
  week52_low: number;
};

type ComparePoint = {
  date: string;
  symbol1_close: number;
  symbol2_close: number;
  symbol1_return_pct: number;
  symbol2_return_pct: number;
};

type ComparePayload = {
  symbol1: string;
  symbol2: string;
  points: ComparePoint[];
};

type ChartSeries = {
  label: string;
  color: string;
  values: number[];
};

const DAY_OPTIONS = [30, 90, 180, 365] as const;

function apiUrl(path: string): string {
  const base = process.env.NEXT_PUBLIC_API_BASE_URL?.trim();
  if (!base && process.env.NODE_ENV === "development") {
    return `http://127.0.0.1:8000${path}`;
  }
  if (!base) {
    return path;
  }
  return `${base.replace(/\/$/, "")}${path}`;
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(apiUrl(path), init);
  } catch {
    throw new Error("Cannot reach API. Start FastAPI with npm run api:dev.");
  }
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const body = (await response.json()) as { detail?: string };
      if (body?.detail) {
        message = body.detail;
      }
    } catch {
      // Keep fallback message.
    }
    throw new Error(message);
  }
  return (await response.json()) as T;
}

function compact(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) {
    return "-";
  }
  return value.toLocaleString(undefined, {
    maximumFractionDigits: 2,
  });
}

function percent(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) {
    return "-";
  }
  return `${(value * 100).toFixed(2)}%`;
}

function utcDate(value: string): string {
  return new Date(`${value}T00:00:00Z`).toLocaleDateString();
}

function LineChart({ labels, series }: { labels: string[]; series: ChartSeries[] }) {
  if (!labels.length || !series.length) {
    return (
      <div className="rounded-2xl border border-white/50 bg-white/80 p-5 text-sm text-slate-600">
        No chart data yet.
      </div>
    );
  }

  const width = 960;
  const height = 360;
  const padding = 36;
  const flatValues = series.flatMap((item) => item.values).filter((v) => Number.isFinite(v));
  const min = Math.min(...flatValues);
  const max = Math.max(...flatValues);
  const spread = max - min || 1;

  const xFor = (i: number) => {
    if (labels.length === 1) {
      return width / 2;
    }
    return padding + (i / (labels.length - 1)) * (width - padding * 2);
  };

  const yFor = (value: number) => {
    const t = (value - min) / spread;
    return height - padding - t * (height - padding * 2);
  };

  return (
    <div className="rounded-2xl border border-white/50 bg-white/80 p-4">
      <svg viewBox={`0 0 ${width} ${height}`} className="h-auto w-full">
        <rect x="0" y="0" width={width} height={height} fill="transparent" />
        {[0, 0.25, 0.5, 0.75, 1].map((tick) => {
          const y = padding + tick * (height - padding * 2);
          return (
            <line
              key={tick}
              x1={padding}
              y1={y}
              x2={width - padding}
              y2={y}
              stroke="#dbe2ec"
              strokeWidth="1"
            />
          );
        })}

        {series.map((s) => {
          const points = s.values.map((value, index) => `${xFor(index)},${yFor(value)}`).join(" ");
          return (
            <polyline
              key={s.label}
              fill="none"
              stroke={s.color}
              strokeWidth="3"
              strokeLinejoin="round"
              strokeLinecap="round"
              points={points}
            />
          );
        })}
      </svg>
      <div className="mt-2 flex flex-wrap gap-3 text-xs text-slate-700">
        {series.map((s) => (
          <div key={s.label} className="inline-flex items-center gap-2 rounded-full bg-slate-100 px-3 py-1">
            <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: s.color }} />
            <span>{s.label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function Home() {
  const [companies, setCompanies] = useState<Company[]>([]);
  const [selectedSymbol, setSelectedSymbol] = useState<string>("");
  const [compareSymbol, setCompareSymbol] = useState<string>("");
  const [days, setDays] = useState<number>(30);
  const [loading, setLoading] = useState<boolean>(false);
  const [refreshing, setRefreshing] = useState<boolean>(false);
  const [error, setError] = useState<string>("");
  const [toast, setToast] = useState<string>("");

  const [points, setPoints] = useState<StockPoint[]>([]);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [compare, setCompare] = useState<ComparePayload | null>(null);

  async function loadCompanies() {
    const list = await requestJson<Company[]>("/api/companies");
    setCompanies(list);

    if (!list.length) {
      return;
    }
    if (!selectedSymbol) {
      setSelectedSymbol(list[0].symbol);
    }
    if (!compareSymbol && list.length > 1) {
      setCompareSymbol(list[1].symbol);
    }
  }

  async function loadSelectedData(symbol: string, selectedDays: number) {
    const [dataPayload, summaryPayload] = await Promise.all([
      requestJson<StockPoint[]>(`/api/data/${encodeURIComponent(symbol)}?days=${selectedDays}`),
      requestJson<Summary>(`/api/summary/${encodeURIComponent(symbol)}`),
    ]);
    setPoints(dataPayload);
    setSummary(summaryPayload);
  }

  async function loadCompare(symbol1: string, symbol2: string, selectedDays: number) {
    if (!symbol1 || !symbol2 || symbol1 === symbol2) {
      setCompare(null);
      return;
    }

    const payload = await requestJson<ComparePayload>(
      `/api/compare?symbol1=${encodeURIComponent(symbol1)}&symbol2=${encodeURIComponent(
        symbol2
      )}&days=${selectedDays}`
    );
    setCompare(payload);
  }

  async function bootstrap() {
    setLoading(true);
    setError("");
    try {
      await loadCompanies();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load companies");
    } finally {
      setLoading(false);
    }
  }

  async function onRefreshData() {
    setRefreshing(true);
    setError("");
    setToast("");

    try {
      await requestJson<{ message: string }>("/api/refresh", { method: "POST" });
      setToast("Data refresh complete.");
      await loadCompanies();

      if (selectedSymbol) {
        await loadSelectedData(selectedSymbol, days);
      }
      if (selectedSymbol && compareSymbol) {
        await loadCompare(selectedSymbol, compareSymbol, days);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Refresh failed");
    } finally {
      setRefreshing(false);
    }
  }

  useEffect(() => {
    void bootstrap();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!selectedSymbol) {
      return;
    }

    let mounted = true;
    setLoading(true);
    setError("");

    void (async () => {
      try {
        await loadSelectedData(selectedSymbol, days);
        if (compareSymbol) {
          await loadCompare(selectedSymbol, compareSymbol, days);
        }
      } catch (err) {
        if (mounted) {
          setError(err instanceof Error ? err.message : "Failed to load symbol data");
        }
      } finally {
        if (mounted) {
          setLoading(false);
        }
      }
    })();

    return () => {
      mounted = false;
    };
  }, [selectedSymbol, compareSymbol, days]);

  const latestPoint = points.length ? points[points.length - 1] : null;

  const priceSeries = useMemo<ChartSeries[]>(() => {
    if (!points.length) {
      return [];
    }
    return [
      {
        label: `${selectedSymbol} Close`,
        color: "#0f766e",
        values: points.map((item) => item.close),
      },
      {
        label: `${selectedSymbol} MA(7)`,
        color: "#f59e0b",
        values: points.map((item) => item.moving_avg_7 ?? item.close),
      },
    ];
  }, [points, selectedSymbol]);

  const compareSeries = useMemo<ChartSeries[]>(() => {
    if (!compare?.points?.length) {
      return [];
    }
    return [
      {
        label: `${compare.symbol1} Return %`,
        color: "#1d4ed8",
        values: compare.points.map((item) => item.symbol1_return_pct),
      },
      {
        label: `${compare.symbol2} Return %`,
        color: "#dc2626",
        values: compare.points.map((item) => item.symbol2_return_pct),
      },
    ];
  }, [compare]);

  return (
    <div className="relative flex min-h-screen flex-1 overflow-hidden">
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_5%_10%,#d7f5f0_0%,transparent_28%),radial-gradient(circle_at_95%_8%,#ffe6bf_0%,transparent_26%),linear-gradient(160deg,#f7fafc_0%,#edf3f7_100%)]" />

      <main className="relative z-10 mx-auto grid w-full max-w-350 grid-cols-1 gap-6 p-4 md:p-6 lg:grid-cols-[300px_1fr]">
        <aside className="rounded-3xl border border-white/40 bg-white/85 p-5 shadow-[0_20px_60px_-40px_rgba(15,23,42,0.45)] backdrop-blur">
          <div className="mb-5">
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">Stock Data</p>
            <h1 className="mt-2 text-2xl font-bold tracking-tight text-slate-900">Market Dashboard</h1>
            <p className="mt-2 text-sm text-slate-600">
              FastAPI analytics with moving averages, volatility, and stock comparison.
            </p>
          </div>

          <button
            type="button"
            onClick={onRefreshData}
            disabled={refreshing}
            className="mb-4 w-full rounded-xl bg-slate-900 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {refreshing ? "Refreshing..." : "Refresh Market Data"}
          </button>

          <div className="mb-4 grid grid-cols-2 gap-2">
            {DAY_OPTIONS.map((value) => (
              <button
                key={value}
                type="button"
                onClick={() => setDays(value)}
                className={`rounded-lg px-3 py-2 text-sm font-medium transition ${
                  days === value
                    ? "bg-teal-600 text-white"
                    : "bg-slate-100 text-slate-700 hover:bg-slate-200"
                }`}
              >
                {value}d
              </button>
            ))}
          </div>

          <div className="space-y-2">
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Companies</p>
            <div className="max-h-90 space-y-2 overflow-y-auto pr-1">
              {companies.map((company) => (
                <button
                  key={company.symbol}
                  type="button"
                  onClick={() => setSelectedSymbol(company.symbol)}
                  className={`w-full rounded-xl border px-3 py-2 text-left transition ${
                    selectedSymbol === company.symbol
                      ? "border-teal-500 bg-teal-50"
                      : "border-slate-200 bg-white hover:border-slate-300"
                  }`}
                >
                  <p className="text-sm font-semibold text-slate-900">{company.symbol}</p>
                  <p className="truncate text-xs text-slate-500">{company.name}</p>
                </button>
              ))}
            </div>
          </div>
        </aside>

        <section className="space-y-6">
          {error ? (
            <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">{error}</div>
          ) : null}
          {toast ? (
            <div className="rounded-2xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-700">
              {toast}
            </div>
          ) : null}

          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <div className="rounded-2xl border border-white/45 bg-white/85 p-4">
              <p className="text-xs uppercase tracking-[0.16em] text-slate-500">Latest Close</p>
              <p className="mt-2 text-2xl font-bold text-slate-900">{compact(summary?.latest_close)}</p>
            </div>
            <div className="rounded-2xl border border-white/45 bg-white/85 p-4">
              <p className="text-xs uppercase tracking-[0.16em] text-slate-500">Average Close (52w)</p>
              <p className="mt-2 text-2xl font-bold text-slate-900">{compact(summary?.average_close)}</p>
            </div>
            <div className="rounded-2xl border border-white/45 bg-white/85 p-4">
              <p className="text-xs uppercase tracking-[0.16em] text-slate-500">52w High / Low</p>
              <p className="mt-2 text-2xl font-bold text-slate-900">
                {compact(summary?.week52_high)} / {compact(summary?.week52_low)}
              </p>
            </div>
            <div className="rounded-2xl border border-white/45 bg-white/85 p-4">
              <p className="text-xs uppercase tracking-[0.16em] text-slate-500">Latest Volatility</p>
              <p className="mt-2 text-2xl font-bold text-slate-900">{percent(latestPoint?.volatility_20d)}</p>
            </div>
          </div>

          <div className="rounded-3xl border border-white/40 bg-white/85 p-4 shadow-[0_24px_60px_-40px_rgba(15,23,42,0.55)]">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="text-lg font-bold text-slate-900">Closing Price Trend</h2>
                <p className="text-sm text-slate-500">{selectedSymbol || "-"} over the last {days} days</p>
              </div>
              <p className="text-xs text-slate-500">{loading ? "Loading..." : `${points.length} data points`}</p>
            </div>

            <LineChart labels={points.map((item) => item.date)} series={priceSeries} />
          </div>

          <div className="rounded-3xl border border-white/40 bg-white/85 p-4 shadow-[0_24px_60px_-40px_rgba(15,23,42,0.55)]">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="text-lg font-bold text-slate-900">Compare Performance</h2>
                <p className="text-sm text-slate-500">Relative returns from first overlapping date</p>
              </div>

              <select
                value={compareSymbol}
                onChange={(e) => setCompareSymbol(e.target.value)}
                className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800"
              >
                <option value="">Select Symbol</option>
                {companies
                  .filter((company) => company.symbol !== selectedSymbol)
                  .map((company) => (
                    <option key={company.symbol} value={company.symbol}>
                      {company.symbol} - {company.name}
                    </option>
                  ))}
              </select>
            </div>

            <LineChart labels={(compare?.points ?? []).map((item) => item.date)} series={compareSeries} />
          </div>

          <div className="rounded-3xl border border-white/40 bg-white/85 p-4 shadow-[0_24px_60px_-40px_rgba(15,23,42,0.55)]">
            <h3 className="mb-3 text-base font-bold text-slate-900">Latest Insight</h3>
            <div className="grid gap-3 sm:grid-cols-3">
              <div className="rounded-xl bg-slate-100 p-3">
                <p className="text-xs uppercase tracking-[0.14em] text-slate-500">Daily Return</p>
                <p className="mt-1 text-lg font-semibold text-slate-900">{percent(latestPoint?.daily_return)}</p>
              </div>
              <div className="rounded-xl bg-slate-100 p-3">
                <p className="text-xs uppercase tracking-[0.14em] text-slate-500">7-Day MA</p>
                <p className="mt-1 text-lg font-semibold text-slate-900">{compact(latestPoint?.moving_avg_7)}</p>
              </div>
              <div className="rounded-xl bg-slate-100 p-3">
                <p className="text-xs uppercase tracking-[0.14em] text-slate-500">Latest Date</p>
                <p className="mt-1 text-lg font-semibold text-slate-900">
                  {latestPoint?.date ? utcDate(latestPoint.date) : "-"}
                </p>
              </div>
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}
