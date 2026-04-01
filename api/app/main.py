from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from .database import Base, engine, get_db
from .schemas import CompareOut, CompanyOut, StockDataPoint, SummaryOut
from .services.market_data import (
    build_comparison,
    build_summary,
    get_companies,
    get_symbol_data,
    refresh_market_data,
)

app = FastAPI(
    title="Stock Data Platform API",
    version="0.2.1",
    description="Single-repo serverless FastAPI API for stock analytics",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup() -> None:
    Base.metadata.create_all(bind=engine)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/refresh")
def refresh(db: Session = Depends(get_db)):
    rows = refresh_market_data(db)
    return {"message": "Data refreshed", "rows_upserted": rows}


@app.get("/api/companies", response_model=list[CompanyOut])
def companies(db: Session = Depends(get_db)):
    return get_companies(db)


@app.get("/api/data/{symbol}", response_model=list[StockDataPoint])
def data(symbol: str, days: int = Query(default=30, ge=1, le=365), db: Session = Depends(get_db)):
    company, rows = get_symbol_data(db, symbol, days)
    if company is None:
        raise HTTPException(status_code=404, detail=f"Unknown symbol '{symbol.upper()}'")
    if not rows:
        raise HTTPException(status_code=404, detail="No data found. Run POST /api/refresh.")

    return [
        {
            "date": r.date,
            "open": r.open,
            "high": r.high,
            "low": r.low,
            "close": r.close,
            "volume": r.volume,
            "daily_return": r.daily_return,
            "moving_avg_7": r.moving_avg_7,
            "week52_high": r.week52_high,
            "week52_low": r.week52_low,
            "volatility_20d": r.volatility_20d,
        }
        for r in rows
    ]


@app.get("/api/summary/{symbol}", response_model=SummaryOut)
def summary(symbol: str, db: Session = Depends(get_db)):
    payload = build_summary(db, symbol)
    if payload is None:
        raise HTTPException(status_code=404, detail=f"No summary found for symbol '{symbol.upper()}'.")
    return payload


@app.get("/api/compare", response_model=CompareOut)
def compare(symbol1: str, symbol2: str, days: int = Query(default=30, ge=5, le=365), db: Session = Depends(get_db)):
    payload = build_comparison(db, symbol1, symbol2, days)
    if payload is None:
        raise HTTPException(status_code=404, detail="Could not compare symbols. Run POST /api/refresh first.")
    return payload
