"""Security primitives: hashing, tokens, origin validation."""

from __future__ import annotations

import hashlib
from typing import Any

import pytest

from app.core.config import Settings
from app.core.security import (
    hash_password,
    hash_token,
    needs_rehash,
    new_csrf_token,
    new_session_token,
    normalise_origin,
    origin_allowed,
    tokens_match,
    verify_password,
)

FAST: dict[str, Any] = {"password_hash_time_cost": 1, "password_hash_memory_kib": 1024, "password_hash_parallelism": 1}


def _settings(**overrides: Any) -> Settings:
    return Settings(_env_file=None, **{**FAST, **overrides})


class TestPasswords:
    def test_argon2id_round_trip(self) -> None:
        settings = _settings()
        hashed = hash_password(settings, "a long passphrase")
        assert hashed.startswith("$argon2id$")
        assert verify_password(settings, hashed, "a long passphrase")
        assert not verify_password(settings, hashed, "a long passphrasE")

    def test_same_password_hashes_differently(self) -> None:
        settings = _settings()
        assert hash_password(settings, "x" * 12) != hash_password(settings, "x" * 12)

    @pytest.mark.parametrize("garbage", ["", "not-a-hash", "$argon2id$v=19$m=1,t=1,p=1$broken"])
    def test_malformed_hash_never_verifies(self, garbage: str) -> None:
        assert not verify_password(_settings(), garbage, "anything")

    def test_rehash_needed_when_parameters_change(self) -> None:
        old = hash_password(_settings(), "passphrase-123")
        assert needs_rehash(_settings(password_hash_memory_kib=2048), old)
        assert not needs_rehash(_settings(), old)


class TestTokens:
    def test_tokens_are_long_and_unique(self) -> None:
        tokens = {new_session_token() for _ in range(200)}
        assert len(tokens) == 200
        assert all(len(token) >= 43 for token in tokens)  # 32 random bytes, base64url
        assert new_csrf_token() != new_csrf_token()

    def test_hash_token_is_sha256_hex(self) -> None:
        assert hash_token("abc") == hashlib.sha256(b"abc").hexdigest()

    @pytest.mark.parametrize(("provided", "expected"), [("tok", True), ("tok2", False), ("", False), (None, False)])
    def test_tokens_match(self, provided: str | None, expected: bool) -> None:
        assert tokens_match("tok", provided) is expected


class TestOrigins:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("https://App.Example.com", "https://app.example.com"),
            ("https://app.example.com:443/path?q=1", "https://app.example.com"),
            ("http://localhost:5173/", "http://localhost:5173"),
            ("javascript:alert(1)", None),
            ("null", None),
            ("", None),
        ],
    )
    def test_normalise_origin(self, raw: str, expected: str | None) -> None:
        assert normalise_origin(raw) == expected

    def _allowed(self, origin: str | None = None, referer: str | None = None) -> bool:
        return origin_allowed(
            origin_header=origin,
            referer_header=referer,
            own_origin="https://api.example.com",
            allowed=["https://app.example.com"],
        )

    def test_allow_listed_origin(self) -> None:
        assert self._allowed("https://app.example.com")

    def test_own_origin(self) -> None:
        assert self._allowed("https://api.example.com")

    @pytest.mark.parametrize(
        "origin",
        ["https://evil.example.com", "http://app.example.com", "https://app.example.com.evil.net", "null"],
    )
    def test_untrusted_origins_rejected(self, origin: str) -> None:
        assert not self._allowed(origin)

    def test_referer_used_when_origin_missing(self) -> None:
        assert self._allowed(referer="https://app.example.com/history")
        assert not self._allowed(referer="https://evil.example.com/page")

    def test_non_browser_request_without_origin_or_referer_passes_origin_check(self) -> None:
        assert self._allowed()
