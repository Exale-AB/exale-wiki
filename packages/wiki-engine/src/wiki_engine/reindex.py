"""Rebuild the derived vector index from the markdown system of record (T06).

Markdown is authoritative; the pgvector index is derived and rebuildable. Run this
after bulk markdown edits, a git restore, or first enabling embeddings, so semantic
recall reflects the current pages.

    python -m wiki_engine.reindex        # reads WIKI_REPO_PATH + WIKI_DB_URL/...

Idempotent (upserts). (Pruning of orphaned vectors is a future addition — it needs
a ``slugs()``/``delete()`` on the store, which ``PgVectorStore`` doesn't expose yet.)
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .protocols import Embedder
from .repo import WikiRepo
from .retrieval import VectorStore

__all__ = ["ReindexResult", "reindex"]


@dataclass(frozen=True)
class ReindexResult:
    embedded: int


def reindex(repo: WikiRepo, embedder: Embedder, store: VectorStore) -> ReindexResult:
    """Embed every current page and upsert into the vector store (idempotent)."""
    pages = repo.list_pages()
    for page in pages:
        store.upsert(page.slug, embedder.embed([page.body])[0])
    return ReindexResult(embedded=len(pages))


def main() -> None:  # pragma: no cover - CLI entry, needs a live model + DB
    from .embed_backends import build_retrieval

    repo = WikiRepo(Path(os.environ.get("WIKI_REPO_PATH", "wiki")))
    embedder, store = build_retrieval()
    result = reindex(repo, embedder, store)
    print(f"reindex: embedded {result.embedded} page(s)")


if __name__ == "__main__":
    main()
