from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import inspect

from app.core.config import settings
from app.core.session import SignedCookieSessionMiddleware
from app.db import Base, engine, SessionLocal
from app.routes.auth import router as auth_router
from app.routes.admin import router as admin_router
from app.routes.public import router as public_router
from app.services import seed_admin_users

logger = logging.getLogger(__name__)


def _sqlite_schema_needs_recreate() -> bool:
    if not settings.is_sqlite:
        return False
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    expected_tables = set(Base.metadata.tables.keys())
    if not existing_tables:
        return False
    if not expected_tables.issubset(existing_tables):
        return True
    for table_name, table in Base.metadata.tables.items():
        existing_columns = {column["name"] for column in inspector.get_columns(table_name)}
        expected_columns = set(table.columns.keys())
        if not expected_columns.issubset(existing_columns):
            return True
    return False


@asynccontextmanager
async def lifespan(app: FastAPI):
    if _sqlite_schema_needs_recreate():
        Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    if settings.is_sqlite:
        logger.info("Database in use: SQLite local (%s)", settings.resolved_database_url)
    elif settings.database_env == "neon":
        logger.info("Database in use: Neon PostgreSQL (%s)", engine.url.render_as_string(hide_password=True))
    else:
        logger.info("Database in use: %s (%s)", engine.url.get_backend_name(), engine.url.render_as_string(hide_password=True))
    if settings.admin_email_allowlist:
        with SessionLocal() as db:
            seed_admin_users(db, settings.admin_email_allowlist, settings.admin_local_accounts)
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    SignedCookieSessionMiddleware,
    secret_key=settings.secret_key,
    https_only=settings.session_cookie_secure,
    same_site="lax",
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(auth_router)
app.include_router(public_router)
app.include_router(admin_router)


@app.get("/")
def root() -> RedirectResponse:
    return RedirectResponse(url=f"/r/{settings.public_token}", status_code=303)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
