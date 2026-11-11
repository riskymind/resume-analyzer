"""Centralised, validated application configuration.

All environment access goes through :class:`Settings`. Production
misconfiguration fails fast at startup with a readable message instead of
surfacing later as a confusing request-time error.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
DEFAULT_SQLITE_PATH = BACKEND_DIR / "data" / "resume_analyzer.db"
DEFAULT_DATABASE_URL = f"sqlite:///{DEFAULT_SQLITE_PATH.as_posix()}"

AppEnv = Literal["development", "test", "production"]


class Settings(BaseSettings):
    """Typed settings loaded from environment variables (and ``backend/.env`` locally)."""

    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Application -------------------------------------------------------
    app_env: AppEnv = "development"
    log_level: str = "INFO"
    log_format: Literal["json", "text"] | None = None
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173"]
    # Shared secret between the frontend proxy (Vercel) and this API. When set, every request except
    # the liveness probe (/api/v1/health) must carry it in the X-Backend-Access-Key header; requests sent
    # straight to the API host are refused. REQUIRED in production (start-up fails without it); unset by
    # default elsewhere, which disables the check. Never give it to the browser.
    backend_access_key: SecretStr | None = None

    # --- Database ----------------------------------------------------------
    database_url: str = DEFAULT_DATABASE_URL
    auto_migrate: bool | None = None

    # --- AI provider -------------------------------------------------------
    ai_provider: Literal["gemini"] = "gemini"
    # Operator kill switch. False: no AI client is built, so no request reaches the provider (generation or
    # embeddings) even with a key configured; AI routes answer 503 and readiness reports "disabled".
    # Lets a deployment hold its production key while live AI usage awaits authorization.
    ai_calls_enabled: bool = True
    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-3.6-flash"
    ai_timeout_seconds: float = Field(default=60, gt=0, le=300)
    ai_max_retries: int = Field(default=2, ge=0, le=5)
    # One deadline for a whole AI call, retries and back-off included. Each attempt gets the
    # smaller of AI_TIMEOUT_SECONDS and the time left; no retry starts once it has passed.
    ai_total_timeout_seconds: float = Field(default=90, gt=0, le=600)
    # Semantic skill matching (Milestone 4). When disabled or failing, matching is deterministic-only
    # and the report says so.
    semantic_matching_enabled: bool = True
    gemini_embedding_model: str = "gemini-embedding-001"
    embedding_dimensions: int = Field(default=768, ge=64, le=3072)
    # Upper bound on texts embedded for one match (skill names plus experience bullets).
    embedding_max_texts: int = Field(default=150, ge=10, le=1000)

    # --- Uploads -----------------------------------------------------------
    max_upload_bytes: int = Field(default=5 * 1024 * 1024, gt=0)
    max_request_bytes: int = Field(default=12 * 1024 * 1024, gt=0)
    max_pdf_pages: int = Field(default=20, gt=0)
    # Resumes with more extracted text than this are rejected (about 12+ pages of dense text).
    max_resume_chars: int = Field(default=40_000, gt=1000)
    # PDFs with fewer letters/digits than this (or 20 per page) are treated as scanned images.
    min_pdf_text_chars: int = Field(default=40, ge=1)
    # Job descriptions longer than this are rejected; shorter than the minimum are too thin to match.
    max_job_description_chars: int = Field(default=30_000, gt=1000)
    min_job_description_chars: int = Field(default=30, ge=1)

    # --- Authentication / sessions ----------------------------------------
    # Absolute lifetime and inactivity timeout of a login session.
    session_ttl_hours: int = Field(default=168, gt=0, le=24 * 90)
    session_idle_timeout_hours: int = Field(default=24, gt=0, le=24 * 90)
    # Secure-only cookies. Defaults to true in production; must stay true there.
    cookie_secure: bool | None = None
    # Argon2id cost parameters (RFC 9106 "second recommended option" by default).
    password_hash_time_cost: int = Field(default=3, ge=1)
    password_hash_memory_kib: int = Field(default=65536, ge=8)
    password_hash_parallelism: int = Field(default=4, ge=1)

    # --- Rate limits (shared via the database, so they hold across workers/instances)
    login_max_attempts_per_ip: int = Field(default=20, ge=1)  # per 15 minutes
    login_max_attempts_per_email: int = Field(default=10, ge=1)  # per 15 minutes
    register_max_per_ip: int = Field(default=5, ge=1)  # per hour
    ai_max_requests_per_minute: int = Field(default=5, ge=1)  # per user
    ai_max_requests_per_day: int = Field(default=50, ge=1)  # per user
    export_max_per_minute: int = Field(default=10, ge=1)  # PDF/DOCX exports per user

    # --- Resume rewriting ----------------------------------------------------
    # Saved versions kept per rewrite (the first generation is always kept).
    rewrite_max_versions: int = Field(default=30, ge=2, le=500)

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("database_url")
    @classmethod
    def _normalise_database_url(cls, value: str) -> str:
        # Render/Heroku-style URLs use the bare "postgres(ql)://" scheme;
        # SQLAlchemy needs the psycopg 3 driver named explicitly.
        for prefix in ("postgres://", "postgresql://"):
            if value.startswith(prefix):
                return "postgresql+psycopg://" + value[len(prefix) :]
        return value

    @field_validator("gemini_api_key", "backend_access_key", mode="before")
    @classmethod
    def _blank_key_is_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def _validate_production(self) -> Settings:
        if not self.is_production:
            return self
        problems: list[str] = []
        if self.gemini_api_key is None:
            problems.append("GEMINI_API_KEY must be set in production.")
        if self.is_sqlite:
            problems.append("DATABASE_URL must point to PostgreSQL in production (SQLite is for local use only).")
        if "*" in self.cors_origins:
            problems.append("CORS_ORIGINS must not contain '*' in production.")
        if any(not origin.startswith("https://") for origin in self.cors_origins):
            problems.append(
                "CORS_ORIGINS must list the public HTTPS frontend origin(s) in production "
                "(e.g. https://your-app.vercel.app); it is also used for CSRF origin checks."
            )
        if self.cookie_secure is False:
            problems.append("COOKIE_SECURE cannot be disabled in production.")
        if self.backend_access_key is None:
            problems.append(
                "BACKEND_ACCESS_KEY must be set in production (the secret the frontend proxy sends; "
                "on Render it is generated by render.yaml)."
            )
        elif len(self.backend_access_key.get_secret_value()) < 32:
            problems.append("BACKEND_ACCESS_KEY must be at least 32 characters (e.g. `openssl rand -hex 32`).")
        if problems:
            raise ValueError("Invalid production configuration: " + " ".join(problems))
        return self

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def effective_log_format(self) -> Literal["json", "text"]:
        if self.log_format is not None:
            return self.log_format
        return "json" if self.is_production else "text"

    @property
    def effective_cookie_secure(self) -> bool:
        return self.is_production if self.cookie_secure is None else self.cookie_secure

    @property
    def session_cookie_name(self) -> str:
        # The __Host- prefix makes browsers enforce Secure, Path=/ and no
        # Domain attribute, so the cookie is bound to exactly the origin that
        # set it (the frontend origin when served through the /api proxy).
        return "__Host-ra_session" if self.effective_cookie_secure else "ra_session"

    @property
    def effective_auto_migrate(self) -> bool:
        if self.auto_migrate is not None:
            return self.auto_migrate
        return not self.is_production


@lru_cache
def get_settings() -> Settings:
    return Settings()
