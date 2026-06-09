from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    pass


database_url = settings.resolved_database_url

engine_kwargs = {
    "future": True,
    "pool_pre_ping": True,
}

if settings.is_sqlite:
    engine_kwargs["connect_args"] = {"check_same_thread": False}
    if "memory" in database_url or database_url.endswith("://"):
        engine_kwargs["poolclass"] = StaticPool

engine = create_engine(database_url, **engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, future=True)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
