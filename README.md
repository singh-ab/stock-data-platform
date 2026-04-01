# Stock Data Platform (Single Repo)

This project uses a single repository for:

- Next.js frontend
- FastAPI backend as a Vercel Python serverless function in `/api/index.py`

## Architecture

- Frontend: Next.js App Router in `/app`
- Backend: FastAPI in `/api/index.py` with code in `/api/app/*`
- Data store: PostgreSQL via `DATABASE_URL`

API endpoints are exposed under `/api/*`:

- `GET /api/health`
- `POST /api/refresh`
- `GET /api/companies`
- `GET /api/data/{symbol}`
- `GET /api/summary/{symbol}`
- `GET /api/compare?symbol1=INFY&symbol2=TCS`

## Environment

Set this in your local `.env` and in Vercel project env vars:

```env
DATABASE_URL=postgresql://username:password@host:5432/database
```

## Local Development

1. Install frontend deps:

```bash
npm install
```

1. Install Python deps (for API runtime parity with Vercel):

```bash
pip install -r requirements.txt
```

1. Start frontend:

```bash
npm run dev
```

1. Start FastAPI in a second terminal:

```bash
npm run api:dev
```

To run frontend and API separately, set `NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000` in `.env`.

By default, this frontend now auto-targets `http://127.0.0.1:8000` in development if `NEXT_PUBLIC_API_BASE_URL` is not set.

Use the dashboard at `http://localhost:3000`.

## Vercel Notes

- `vercel.json` rewrites `/api/(.*)` to the FastAPI serverless function.
- Next.js continues to handle all non-API routes.

## API Code Layout

- `/api/index.py`: serverless entrypoint
- `/api/app/main.py`: FastAPI routes and app wiring
- `/api/app/database.py`: SQLAlchemy engine and DB session
- `/api/app/models.py`: ORM models
- `/api/app/services/market_data.py`: data ingestion and analytics logic

## Feature Coverage

- Data cleaning with Pandas
- Daily Return
- 7-day Moving Average
- 52-week High/Low
- Custom metric: 20-day volatility score

## Frontend Coverage

- Left-panel company selector
- Day filters (30/90/180/365)
- Price trend line chart (close + 7 day moving average)
- Compare chart for two symbols
- Summary cards (latest close, average close, 52-week range, volatility)
- Data refresh action wired to `POST /api/refresh`
