import os

from dotenv import load_dotenv

load_dotenv()


def get_database_url() -> str:
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set.")
    if database_url.startswith("prisma://"):
        raise RuntimeError(
            "DATABASE_URL uses prisma:// which SQLAlchemy cannot use directly. "
            "Use Prisma's direct PostgreSQL URL (postgresql://...)."
        )

    # Accept both postgres:// and postgresql://, then force psycopg driver.
    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql+psycopg://", 1)
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url
