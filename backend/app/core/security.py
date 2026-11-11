"""Security primitives: password hashing, session/CSRF tokens, origin checks."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from functools import lru_cache
from urllib.parse import urlsplit

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import Settings

SESSION_TOKEN_BYTES = 32  # 256 bits from the OS CSPRNG
CSRF_TOKEN_BYTES = 32


@lru_cache(maxsize=8)
def _hasher(time_cost: int, memory_kib: int, parallelism: int) -> PasswordHasher:
    return PasswordHasher(time_cost=time_cost, memory_cost=memory_kib, parallelism=parallelism, type=Type.ID)


def password_hasher(settings: Settings) -> PasswordHasher:
    return _hasher(
        settings.password_hash_time_cost, settings.password_hash_memory_kib, settings.password_hash_parallelism
    )


def hash_password(settings: Settings, password: str) -> str:
    return password_hasher(settings).hash(password)


def verify_password(settings: Settings, password_hash: str, password: str) -> bool:
    try:
        return password_hasher(settings).verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(settings: Settings, password_hash: str) -> bool:
    return password_hasher(settings).check_needs_rehash(password_hash)


@lru_cache(maxsize=8)
def _dummy_hash(time_cost: int, memory_kib: int, parallelism: int) -> str:
    return _hasher(time_cost, memory_kib, parallelism).hash(secrets.token_urlsafe(16))


def burn_password_check(settings: Settings, password: str) -> None:
    """Spend the same time as a real verification (prevents user enumeration by timing)."""

    verify_password(
        settings,
        _dummy_hash(
            settings.password_hash_time_cost, settings.password_hash_memory_kib, settings.password_hash_parallelism
        ),
        password,
    )


def new_session_token() -> str:
    return secrets.token_urlsafe(SESSION_TOKEN_BYTES)


def new_csrf_token() -> str:
    return secrets.token_urlsafe(CSRF_TOKEN_BYTES)


def hash_token(token: str) -> str:
    """SHA-256 is appropriate here: tokens are 256-bit random values, not passwords."""

    return hashlib.sha256(token.encode()).hexdigest()


def tokens_match(expected: str, provided: str | None) -> bool:
    if not provided:
        return False
    return hmac.compare_digest(expected.encode(), provided.encode())


def normalise_origin(value: str) -> str | None:
    """Reduce an Origin/Referer value to ``scheme://host[:port]`` (lowercase)."""

    parts = urlsplit(value.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    default_port = {"http": 80, "https": 443}[parts.scheme]
    port = f":{parts.port}" if parts.port and parts.port != default_port else ""
    return f"{parts.scheme}://{parts.hostname.lower()}{port}"


def origin_allowed(
    *, origin_header: str | None, referer_header: str | None, own_origin: str, allowed: list[str]
) -> bool:
    """Validate the browser-reported request origin for state-changing requests.

    Browsers always send ``Origin`` on cross-origin POSTs and on same-origin
    non-GET fetches. When neither ``Origin`` nor ``Referer`` is present the
    request is not from a browser page (curl, server-to-server), which cannot
    carry a victim's cookies, so it is allowed here; the CSRF token is still
    required for authenticated endpoints.
    """

    if origin_header is not None:
        if origin_header.strip().lower() == "null":
            return False
        claimed = normalise_origin(origin_header)
    elif referer_header:
        claimed = normalise_origin(referer_header)
    else:
        return True
    if claimed is None:
        return False
    trusted = {o for o in (normalise_origin(a) for a in allowed) if o} | {own_origin}
    return claimed in trusted
