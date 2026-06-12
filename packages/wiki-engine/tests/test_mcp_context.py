"""wiki_context: ranked raw context with citations and NO LLM call (T03)."""

from pathlib import Path

from wiki_engine.fakes import FakeEmbedder
from wiki_engine.mcp_server import handle_wiki_context
from wiki_engine.page import Page
from wiki_engine.repo import WikiRepo


class _NoVectors:
    """Structural-only store (mirrors the MCP's FakeVectorStore)."""

    def upsert(self, slug, vector):  # noqa: ANN001
        pass

    def search(self, vector, k):  # noqa: ANN001
        return []


def _seed(tmp_path: Path) -> WikiRepo:
    repo = WikiRepo.init(tmp_path, committer=lambda _r, _m: None)
    repo.write_page(
        Page(
            slug="renewals",
            frontmatter={"title": "Renewals"},
            body="Account renewal process: contracts renew yearly.",
        )
    )
    repo.write_page(
        Page(
            slug="hiring",
            frontmatter={"title": "Hiring"},
            body="Hiring pipeline: interviews then offer.",
        )
    )
    repo.write_index(
        "# Index\n\n## Ops\n"
        "- [[Renewals]] (renewals) — renewal contract process\n"
        "- [[Hiring]] (hiring) — hiring interview pipeline\n"
    )
    return repo


def test_context_returns_raw_pages_and_citations(tmp_path: Path):
    repo = _seed(tmp_path)

    out = handle_wiki_context(
        repo,
        query="renewal contract",
        k=5,
        token_budget=2000,
        vectorstore=_NoVectors(),
        embedder=FakeEmbedder(),
    )

    assert "renewals" in out["citations"]
    items = {c["slug"]: c for c in out["context"]}
    assert items["renewals"]["text"].strip() == "Account renewal process: contracts renew yearly."
    assert items["renewals"]["title"] == "Renewals"


def test_context_respects_token_budget(tmp_path: Path):
    repo = _seed(tmp_path)

    # ~5 tokens => ~20 chars: only the first ranked page fits.
    out = handle_wiki_context(
        repo,
        query="renewal hiring",
        k=5,
        token_budget=5,
        vectorstore=_NoVectors(),
        embedder=FakeEmbedder(),
    )

    total = sum(len(c["text"]) for c in out["context"])
    assert total <= 5 * 4
    assert len(out["context"]) >= 1  # always returns at least the top hit


def test_context_empty_query_returns_empty(tmp_path: Path):
    repo = _seed(tmp_path)

    out = handle_wiki_context(
        repo,
        query="kubernetes helm istio",
        k=5,
        token_budget=2000,
        vectorstore=_NoVectors(),
        embedder=FakeEmbedder(),
    )

    assert out["context"] == []
    assert out["citations"] == []
