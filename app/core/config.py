from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:  # pragma: no cover - fallback for minimal environments
    load_dotenv = None  # type: ignore[assignment]


def _load_environment() -> None:
    if load_dotenv is None:
        return
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if env_path.exists():
        load_dotenv(dotenv_path=env_path, override=False)


_load_environment()


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _split_admin_accounts(value: str | None) -> list[tuple[str, str]]:
    if not value:
        return []
    accounts: list[tuple[str, str]] = []
    for raw_item in value.split(","):
        item = raw_item.strip()
        if not item:
            continue
        if ":" not in item:
            continue
        email, phone = item.split(":", 1)
        email = email.strip()
        phone = phone.strip()
        if email and phone:
            accounts.append((email, phone))
    return accounts


def _normalize_database_env(value: str | None) -> str:
    normalized = (value or "local").strip().lower()
    return normalized or "local"


def _normalize_database_url(value: str | None) -> str:
    if not value:
        return ""
    normalized = value.strip().strip('"').strip("'")
    if normalized.startswith("postgresql://"):
        return "postgresql+psycopg://" + normalized.removeprefix("postgresql://")
    if normalized.startswith("postgres://"):
        return "postgresql+psycopg://" + normalized.removeprefix("postgres://")
    return normalized


@dataclass(slots=True)
class Settings:
    database_env: str = field(default_factory=lambda: _normalize_database_env(os.getenv("DATABASE_ENV")))
    database_url: str = field(default_factory=lambda: _normalize_database_url(os.getenv("DATABASE_URL")))
    database_url_local: str = field(default_factory=lambda: _normalize_database_url(os.getenv("DATABASE_URL_LOCAL", "sqlite:///./clients_qr.db")))
    database_url_neon: str = field(default_factory=lambda: _normalize_database_url(os.getenv("DATABASE_URL_NEON")))
    secret_key: str = field(default_factory=lambda: os.getenv("SECRET_KEY", "dev-secret-change-me"))
    public_token: str = field(default_factory=lambda: os.getenv("PUBLIC_TOKEN", "local-qr"))
    admin_email_allowlist: list[str] = field(default_factory=lambda: _split_csv(os.getenv("ADMIN_EMAIL_ALLOWLIST")))
    admin_local_accounts: list[tuple[str, str]] = field(default_factory=lambda: _split_admin_accounts(os.getenv("ADMIN_LOCAL_ACCOUNTS")))
    google_client_id: str = field(default_factory=lambda: os.getenv("GOOGLE_CLIENT_ID", ""))
    google_client_secret: str = field(default_factory=lambda: os.getenv("GOOGLE_CLIENT_SECRET", ""))
    google_redirect_path: str = field(default_factory=lambda: os.getenv("GOOGLE_REDIRECT_PATH", "/auth/admin/google/callback"))
    public_google_redirect_path: str = field(default_factory=lambda: os.getenv("PUBLIC_GOOGLE_REDIRECT_PATH", "/auth/public/google/callback"))
    session_cookie_secure: bool = field(default_factory=lambda: _env_bool("SESSION_COOKIE_SECURE", False))
    app_name: str = field(default_factory=lambda: os.getenv("APP_NAME", "Clients QR"))
    app_env: str = field(default_factory=lambda: os.getenv("APP_ENV", "development"))

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        if self.database_env == "neon" and self.database_url_neon:
            return self.database_url_neon
        return self.database_url_local

    @property
    def is_sqlite(self) -> bool:
        return self.resolved_database_url.startswith("sqlite")

    @property
    def has_google_oauth(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)

    @property
    def has_local_admin_accounts(self) -> bool:
        return bool(self.admin_local_accounts)

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"


settings = Settings()
