from datetime import date

from pydantic import BaseModel


class CompanyOut(BaseModel):
    symbol: str
    name: str
    exchange: str


class StockDataPoint(BaseModel):
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: int
    daily_return: float | None
    moving_avg_7: float | None
    week52_high: float | None
    week52_low: float | None
    volatility_20d: float | None


class SummaryOut(BaseModel):
    symbol: str
    days_covered: int
    latest_close: float
    average_close: float
    week52_high: float
    week52_low: float


class ComparePoint(BaseModel):
    date: date
    symbol1_close: float
    symbol2_close: float
    symbol1_return_pct: float
    symbol2_return_pct: float


class CompareOut(BaseModel):
    symbol1: str
    symbol2: str
    points: list[ComparePoint]


class BriefingOut(BaseModel):
    symbol: str
    summary: str
    model: str
    headlines_used: int
    headlines_lookback_days: int
    generated_at: str
