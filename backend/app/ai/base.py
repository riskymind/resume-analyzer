"""Provider-neutral AI interface.

Business logic depends only on :class:`AIProvider`. Adding another provider
means writing one adapter class and registering it in ``app.ai.factory``;
services and routes do not change.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


class AIProviderError(Exception):
    """A provider call failed (network, timeout, quota, safety block, empty output).

    The message is safe to show to users: adapters must not include prompt
    content or credentials in it.
    """

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


@runtime_checkable
class AIProvider(Protocol):
    name: str

    def generate_json(
        self,
        *,
        system: str,
        prompt: str,
        json_schema: dict[str, Any] | None = None,
        max_output_tokens: int | None = None,
        task: str = "generate",
    ) -> str:
        """Return the model's raw JSON text for ``prompt`` under ``system`` instructions.

        ``json_schema`` constrains the output shape where the provider supports it,
        ``max_output_tokens`` caps the reply (a truncated reply is an error), and
        ``task`` is a short label used only in logs.

        Callers are responsible for parsing and validating the returned text.
        Raises :class:`AIProviderError` on any failure.
        """
        ...


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Text embeddings for semantic similarity. Optional: matching degrades to deterministic-only without it."""

    name: str
    embedding_model: str
    embedding_dimensions: int

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one vector per input text, in order. Raises :class:`AIProviderError` on any failure."""
        ...
