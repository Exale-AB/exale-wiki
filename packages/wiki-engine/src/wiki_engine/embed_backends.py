"""Embeddings + vector-store wiring for semantic retrieval.

The engine's retrieval is hybrid: structural navigation first, then vector recall.
This module supplies the vector half — a local embedding model (``fastembed``,
in-process, no external API, EU-residency-friendly) plus a pgvector-backed store.

Config is env-driven so the seat wrapper controls it:

- ``WIKI_EMBED_MODEL`` — fastembed model id (default ``BAAI/bge-small-en-v1.5``).
- ``WIKI_EMBED_DIM``   — embedding dimension (default 384, matching the model).
- ``WIKI_DB_URL`` / ``DATABASE_URL`` — pgvector DSN.
- ``WIKI_EMBED_DISABLED`` — set truthy to force structural-only retrieval.

``build_judgment``'s sibling: every path degrades gracefully. If fastembed isn't
installed, the DB is unreachable, or embeddings are disabled, retrieval falls back
to ``FakeEmbedder`` + ``NullVectorStore`` (structural-only) and warns to stderr —
the MCP never crashes for lack of a model or database.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Sequence

from .fakes import FakeEmbedder
from .protocols import Embedder
from .retrieval import NullVectorStore, PgVectorStore, VectorStore

__all__ = ["LocalEmbedder", "build_retrieval"]

_DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"
_DEFAULT_DIM = 384
_TABLE = "wiki_vectors"


def _warn(message: str) -> None:
    print(f"[wiki_engine.embed_backends] {message}", file=sys.stderr, flush=True)


def _truthy(value: str) -> bool:
    return value.strip().lower() not in ("", "0", "false", "no")


class LocalEmbedder(Embedder):  # pragma: no cover - requires fastembed + model download
    """In-process embeddings via fastembed (ONNX). Lazily loads the model.

    Uses a stable on-disk cache (``WIKI_EMBED_CACHE``) so the model is downloaded
    once and persists — the default fastembed temp cache lives under ``/var/folders``
    and is prone to partial/evicted downloads.
    """

    def __init__(self, *, model: str = _DEFAULT_MODEL, dim: int = _DEFAULT_DIM) -> None:
        from fastembed import TextEmbedding  # type: ignore[import-not-found]

        cache_dir = os.environ.get("WIKI_EMBED_CACHE") or None
        self._model = TextEmbedding(model_name=model, cache_dir=cache_dir)
        self.dim = dim

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [[float(x) for x in vec] for vec in self._model.embed(list(texts))]


def build_retrieval() -> tuple[Embedder, VectorStore]:
    """Return ``(embedder, store)`` for the MCP server to inject into ingest/query.

    Hermes-grade semantic retrieval (LocalEmbedder + PgVectorStore) when the model,
    DB, and config are all available; otherwise structural-only fakes.
    """
    if _truthy(os.environ.get("WIKI_EMBED_DISABLED", "")):
        _warn("WIKI_EMBED_DISABLED set — structural-only retrieval")
        return FakeEmbedder(), NullVectorStore()

    model = os.environ.get("WIKI_EMBED_MODEL", _DEFAULT_MODEL)
    dim = int(os.environ.get("WIKI_EMBED_DIM", _DEFAULT_DIM))
    dsn = os.environ.get("WIKI_DB_URL") or os.environ.get("DATABASE_URL")

    try:
        if not dsn:
            raise RuntimeError("no WIKI_DB_URL/DATABASE_URL configured")
        embedder = LocalEmbedder(model=model, dim=dim)
        store = PgVectorStore(dsn, dim=dim, table=_TABLE)
        store.ensure_schema()
    except Exception as exc:  # noqa: BLE001 - degrade to structural-only, never crash
        _warn(f"semantic retrieval unavailable ({exc}); structural-only")
        return FakeEmbedder(), NullVectorStore()

    # pragma: no cover - reached only with a live model + database
    _warn(f"semantic retrieval enabled — model '{model}' (dim {dim}), pgvector @ {dsn}")
    return embedder, store  # pragma: no cover
