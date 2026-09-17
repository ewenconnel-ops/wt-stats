"""
Database engine + session factory.

DATABASE_URL example:
    postgresql+psycopg://wt_stats:password@localhost:5432/wt_stats
"""
import os
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+psycopg://wt_stats:wt_stats@localhost:5432/wt_stats"
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=10, max_overflow=20)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency: yields a session, always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
