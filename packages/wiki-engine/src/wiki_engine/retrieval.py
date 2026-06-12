"""Retrieval: the derived vector index + hybrid (structural + vector) search.

Markdown is the system of record; this index is rebuildable from it. The
``VectorStore`` seam lets unit tests use a pure-Python in-memory store while the
psycopg/pgvector store (Task 9) is exercised only in the integration tier.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from . import catalog
from .protocols import Embedder
from .repo import WikiRepo
from .slug import slugify

__all__ = [
    "InMemoryVectorStore",
    "NullVectorStore",
    "PgVectorStore",
    "Retrieved",
    "Retriever",
    "VectorStore",
    "cosine",
    "format_vector",
]


@dataclass(frozen=True)
class Retrieved:
    slug: str
    score: float


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def format_vector(vector: Sequence[float]) -> str:
    """Render a vector as a pgvector literal, e.g. ``[1.0,2.5,-3.0]``."""
    return "[" + ",".join(str(float(x)) for x in vector) + "]"


class VectorStore(Protocol):
    def upsert(self, slug: str, vector: Sequence[float]) -> None: ...
    def search(self, vector: Sequence[float], k: int) -> list[Retrieved]: ...


class NullVectorStore:
    """No-op store: ignores upserts, returns no hits (structural-only retrieval).

    The graceful fallback when no embedder/DB is available — retrieval degrades to
    structural navigation instead of crashing.
    """

    def upsert(self, slug: str, vector: Sequence[float]) -> None:
        pass

    def search(self, vector: Sequence[float], k: int) -> list[Retrieved]:
        return []


class InMemoryVectorStore:
    """Deterministic in-process store; cosine ranking over stored vectors."""

    def __init__(self) -> None:
        self._vectors: dict[str, list[float]] = {}

    def upsert(self, slug: str, vector: Sequence[float]) -> None:
        self._vectors[slug] = [float(x) for x in vector]

    def search(self, vector: Sequence[float], k: int) -> list[Retrieved]:
        scored = [Retrieved(slug, cosine(vector, stored)) for slug, stored in self._vectors.items()]
        scored.sort(key=lambda r: (-r.score, r.slug))
        return scored[:k]


class Retriever:
    """Hybrid retrieval: structural navigation first, vector recall second."""

    def __init__(self, *, repo: WikiRepo, store: VectorStore, embedder: Embedder) -> None:
        self._repo = repo
        self._store = store
        self._embedder = embedder

    def structural(self, question: str, *, k: int) -> list[str]:
        tokens = {t for t in question.lower().split() if t}
        entries = catalog.parse_index(self._repo.read_index())

        scored: list[tuple[int, str]] = []
        for entry in entries:
            haystack = f"{entry.title} {entry.summary}".lower()
            overlap = sum(1 for token in tokens if token in haystack)
            if overlap:
                scored.append((overlap, entry.slug))
        scored.sort(key=lambda item: (-item[0], item[1]))
        ranked = [slug for _, slug in scored]

        neighbors: list[str] = []
        for slug in ranked[:k]:
            page = self._repo.read_page(slug)
            if page is None:
                continue
            for link in page.wikilinks:
                neighbor = slugify(link)
                if neighbor and neighbor not in ranked and neighbor not in neighbors:
                    neighbors.append(neighbor)

        return (ranked + neighbors)[:k]

    def retrieve(self, question: str, *, k: int = 5) -> list[str]:
        """Structural hits first (Karpathy-faithful), then vector-only slugs."""
        structural = self.structural(question, k=k)
        query_vector = self._embedder.embed([question])[0]
        vector_slugs = [hit.slug for hit in self._store.search(query_vector, k)]
        merged = structural + [slug for slug in vector_slugs if slug not in structural]
        return merged[:k]


class PgVectorStore:
    """pgvector-backed store (integration tier only).

    Lazily connects on first use so unit tests can construct it and inspect the
    SQL without a live database. The actual connection/execution is excluded
    from coverage (it requires Postgres) — exactly like ``repo._git_commit``.
    The cosine-distance operator ``<=>`` ranks results; score = 1 - distance.
    """

    def __init__(self, dsn: str, *, dim: int, table: str = "wiki_vectors") -> None:
        self.dsn = dsn
        self.dim = dim
        self.table = table
        self._conn: object | None = None

    def _search_sql(self) -> str:
        return (
            f"SELECT slug, 1 - (embedding <=> %s::vector) AS score "
            f"FROM {self.table} ORDER BY embedding <=> %s::vector LIMIT %s"
        )

    def _upsert_sql(self) -> str:
        return (
            f"INSERT INTO {self.table} (slug, embedding) VALUES (%s, %s::vector) "
            f"ON CONFLICT (slug) DO UPDATE SET embedding = EXCLUDED.embedding"
        )

    def _connect(self) -> object:  # pragma: no cover
        if self._conn is None:
            import psycopg

            self._conn = psycopg.connect(self.dsn, autocommit=True)
        return self._conn

    def ensure_schema(self) -> None:  # pragma: no cover
        conn = self._connect()
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")  # type: ignore[attr-defined]
        conn.execute(  # type: ignore[attr-defined]
            f"CREATE TABLE IF NOT EXISTS {self.table} "
            f"(slug text PRIMARY KEY, embedding vector({self.dim}))"
        )

    def upsert(self, slug: str, vector: Sequence[float]) -> None:  # pragma: no cover
        self._connect().execute(  # type: ignore[attr-defined]
            self._upsert_sql(), (slug, format_vector(vector))
        )

    def search(self, vector: Sequence[float], k: int) -> list[Retrieved]:  # pragma: no cover
        literal = format_vector(vector)
        rows = (
            self._connect()
            .execute(  # type: ignore[attr-defined]
                self._search_sql(), (literal, literal, k)
            )
            .fetchall()
        )  # type: ignore[attr-defined]
        return [Retrieved(slug=row[0], score=float(row[1])) for row in rows]
