from __future__ import annotations

from app.core.config import Settings


def test_resolved_database_url_prefers_explicit_override(monkeypatch):
    monkeypatch.setenv("DATABASE_ENV", "neon")
    monkeypatch.setenv("DATABASE_URL", "postgresql://override.example/db")
    monkeypatch.setenv("DATABASE_URL_LOCAL", "sqlite:///./clients_qr.db")
    monkeypatch.setenv("DATABASE_URL_NEON", "postgresql://neon.example/db")

    settings = Settings()

    assert settings.resolved_database_url == "postgresql+psycopg://override.example/db"
    assert settings.is_sqlite is False


def test_resolved_database_url_uses_local_sqlite_by_default(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL_NEON", raising=False)
    monkeypatch.setenv("DATABASE_ENV", "local")
    monkeypatch.setenv("DATABASE_URL_LOCAL", "sqlite:///./clients_qr.db")

    settings = Settings()

    assert settings.resolved_database_url == "sqlite:///./clients_qr.db"
    assert settings.is_sqlite is True


def test_resolved_database_url_uses_neon_url_when_selected(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_ENV", "neon")
    monkeypatch.setenv("DATABASE_URL_LOCAL", "sqlite:///./clients_qr.db")
    monkeypatch.setenv("DATABASE_URL_NEON", "postgresql://neon.example/db")

    settings = Settings()

    assert settings.resolved_database_url == "postgresql+psycopg://neon.example/db"
    assert settings.is_sqlite is False


def test_resolved_database_url_normalizes_quoted_postgres_urls(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("DATABASE_ENV", "neon")
    monkeypatch.setenv("DATABASE_URL_LOCAL", "sqlite:///./clients_qr.db")
    monkeypatch.setenv("DATABASE_URL_NEON", "'postgresql://neon.example/db?sslmode=require'")

    settings = Settings()

    assert settings.resolved_database_url == "postgresql+psycopg://neon.example/db?sslmode=require"
