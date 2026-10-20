"""Shared SQLAlchemy engine configuration."""

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, URL, make_url


def create_database_engine(database_url: str | URL) -> Engine:
    """Create a pooled engine, selecting psycopg 3 for PostgreSQL URLs."""
    url = make_url(database_url)
    if url.drivername in {"postgres", "postgresql"}:
        url = url.set(drivername="postgresql+psycopg")
    return create_engine(url, pool_pre_ping=True)
