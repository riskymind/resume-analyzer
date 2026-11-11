"""Settings validation: production fail-fast rules and URL normalisation."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from app.core.config import Settings

PG = "postgresql://user:pw@db.example.com:5432/app"


def build(**values: Any) -> Settings:
    return Settings(_env_file=None, **values)


def test_development_defaults_use_sqlite_and_auto_migrate() -> None:
    settings = build(app_env="development", gemini_api_key=None)
    assert settings.is_sqlite
    assert settings.effective_auto_migrate is True
    assert settings.effective_log_format == "text"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("postgres://u:p@h/db", "postgresql+psycopg://u:p@h/db"),
        ("postgresql://u:p@h/db", "postgresql+psycopg://u:p@h/db"),
        ("postgresql+psycopg://u:p@h/db", "postgresql+psycopg://u:p@h/db"),
        ("sqlite:///./x.db", "sqlite:///./x.db"),
    ],
)
def test_database_url_normalisation(raw: str, expected: str) -> None:
    assert build(database_url=raw).database_url == expected


def test_production_requires_ai_key() -> None:
    with pytest.raises(ValidationError, match="GEMINI_API_KEY must be set"):
        build(app_env="production", database_url=PG)


def test_production_rejects_sqlite() -> None:
    with pytest.raises(ValidationError, match="must point to PostgreSQL"):
        build(app_env="production", gemini_api_key="k", database_url="sqlite:///x.db")


def test_production_rejects_wildcard_cors() -> None:
    with pytest.raises(ValidationError, match="must not contain"):
        build(app_env="production", gemini_api_key="k", database_url=PG, cors_origins="*")


def test_valid_production_settings() -> None:
    settings = build(
        app_env="production",
        gemini_api_key="k",
        database_url=PG,
        cors_origins="https://app.example.com",
        backend_access_key="k" * 32,
    )
    assert settings.effective_auto_migrate is False
    assert settings.effective_log_format == "json"
    assert settings.cors_origins == ["https://app.example.com"]


def test_cors_origins_parse_comma_separated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "https://a.example.com, https://b.example.com")
    assert build().cors_origins == ["https://a.example.com", "https://b.example.com"]


def test_blank_api_key_is_treated_as_missing() -> None:
    assert build(gemini_api_key="   ").gemini_api_key is None


def test_api_key_is_not_exposed_in_repr() -> None:
    settings = build(gemini_api_key="super-secret-key")
    assert "super-secret-key" not in repr(settings)
    assert "super-secret-key" not in str(settings.model_dump())


def test_production_requires_https_frontend_origins() -> None:
    with pytest.raises(ValidationError, match="public HTTPS frontend origin"):
        build(app_env="production", gemini_api_key="k", database_url=PG, cors_origins="http://localhost:5173")


def test_production_cannot_disable_secure_cookies() -> None:
    with pytest.raises(ValidationError, match="COOKIE_SECURE cannot be disabled"):
        build(
            app_env="production",
            gemini_api_key="k",
            database_url=PG,
            cors_origins="https://app.example.com",
            cookie_secure=False,
        )


def test_cookie_security_defaults() -> None:
    production = build(
        app_env="production",
        gemini_api_key="k",
        database_url=PG,
        cors_origins="https://a.example.com",
        backend_access_key="k" * 32,
    )
    assert production.effective_cookie_secure is True
    assert production.session_cookie_name == "__Host-ra_session"
    local = build(app_env="development")
    assert local.effective_cookie_secure is False
    assert local.session_cookie_name == "ra_session"
