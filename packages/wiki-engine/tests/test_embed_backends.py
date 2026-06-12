"""Semantic retrieval wiring (T05): vector recall + graceful fallback.

A deterministic stub embedder stands in for fastembed, so these run with no model
download and no database — they exercise the hybrid retriever's vector path and the
fallback behaviour of build_retrieval().
"""

from pathlib import Path

import pytest

from wiki_engine.embed_backends import build_retrieval
from wiki_engine.mcp_server import handle_wiki_context, handle_wiki_ingest
from wiki_engine.page import Page
from wiki_engine.repo import WikiRepo
from wiki_engine.retrieval import InMemoryVectorStore, NullVectorStore


class StubEmbedder:
    """Maps text to a topic vector by keyword — so a doc and a query about the same
    topic land on the same axis even with disjoint wording (semantic, not lexical)."""

    def embed(self, texts):  # noqa: ANN001
        return [self._vec(t) for t in texts]

    def _vec(self, text: str) -> list[float]:
        t = text.lower()
        return [
            1.0 if any(w in t for w in ("alpha", "zulu", "yankee")) else 0.0,
            1.0 if any(w in t for w in ("hire", "hiring", "recruit")) else 0.0,
            1.0 if any(w in t for w in ("renew", "contract")) else 0.0,
        ]


def _repo(tmp_path: Path) -> WikiRepo:
    repo = WikiRepo.init(tmp_path, committer=lambda _r, _m: None)
    repo.write_page(
        Page(slug="topic-a", frontmatter={"title": "Topic A"}, body="alpha bravo charlie")
    )
    repo.write_index("# Index\n\n## X\n- [[Topic A]] (topic-a) — alpha bravo charlie\n")
    return repo


def test_vector_recall_finds_non_lexical_match(tmp_path: Path):
    repo = _repo(tmp_path)
    embedder = StubEmbedder()
    store = InMemoryVectorStore()
    store.upsert("topic-a", embedder.embed(["alpha bravo charlie"])[0])

    # Query shares no words with the page's title/summary — only the vector matches.
    out = handle_wiki_context(repo, query="zulu yankee", vectorstore=store, embedder=embedder)

    assert "topic-a" in out["citations"]


def test_ingest_writes_an_embedding(tmp_path: Path):
    repo = WikiRepo.init(tmp_path, committer=lambda _r, _m: None)
    embedder = StubEmbedder()
    store = InMemoryVectorStore()

    result = handle_wiki_ingest(
        repo,
        source_text="renew the contract",
        source_url=None,
        category="ops",
        embedder=embedder,
        store=store,
    )

    # The page slug is now searchable in the vector store.
    hits = store.search(embedder.embed(["renew the contract"])[0], k=3)
    assert any(h.slug == result["slug"] for h in hits)


def test_build_retrieval_falls_back_when_disabled(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("WIKI_EMBED_DISABLED", "1")

    embedder, store = build_retrieval()

    assert isinstance(store, NullVectorStore)
    assert store.search(embedder.embed(["anything"])[0], k=5) == []


def test_build_retrieval_falls_back_without_db(monkeypatch: pytest.MonkeyPatch):
    # No embeddings disabled flag, but no DB configured → graceful structural-only.
    monkeypatch.delenv("WIKI_EMBED_DISABLED", raising=False)
    monkeypatch.delenv("WIKI_DB_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    _embedder, store = build_retrieval()

    assert isinstance(store, NullVectorStore)
