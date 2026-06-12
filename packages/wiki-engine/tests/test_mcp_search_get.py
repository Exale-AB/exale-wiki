"""wiki_search (ranked metadata, no bodies) and wiki_get (fetch by slug) — T04."""

from pathlib import Path

from wiki_engine.fakes import FakeEmbedder
from wiki_engine.mcp_server import handle_wiki_get, handle_wiki_search
from wiki_engine.page import Page
from wiki_engine.repo import WikiRepo


class _NoVectors:
    def upsert(self, slug, vector):  # noqa: ANN001
        pass

    def search(self, vector, k):  # noqa: ANN001
        return []


def _seed(tmp_path: Path) -> WikiRepo:
    repo = WikiRepo.init(tmp_path, committer=lambda _r, _m: None)
    repo.write_page(
        Page(
            slug="renewals",
            frontmatter={"title": "Renewals", "category": "Ops"},
            body="Account renewal process: contracts renew yearly.",
        )
    )
    repo.write_page(
        Page(
            slug="hiring",
            frontmatter={"title": "Hiring", "category": "People"},
            body="Hiring pipeline.",
        )
    )
    repo.write_index(
        "# Index\n\n## Ops\n"
        "- [[Renewals]] (renewals) — renewal contract process\n"
        "- [[Hiring]] (hiring) — hiring interview pipeline\n"
    )
    return repo


def test_search_ranks_matches_without_bodies(tmp_path: Path):
    repo = _seed(tmp_path)

    out = handle_wiki_search(
        repo, query="renewal contract", k=10, vectorstore=_NoVectors(), embedder=FakeEmbedder()
    )

    slugs = [r["slug"] for r in out["results"]]
    assert "renewals" in slugs
    top = out["results"][0]
    # Search returns catalog metadata, not page bodies.
    assert top["title"] == "Renewals"
    assert "summary" in top and "score" in top
    assert "body" not in top and "text" not in top


def test_get_returns_page(tmp_path: Path):
    repo = _seed(tmp_path)

    out = handle_wiki_get(repo, slug="renewals")

    assert out["found"] is True
    assert out["title"] == "Renewals"
    assert "renewal process" in out["body"]
    assert out["frontmatter"]["category"] == "Ops"


def test_get_unknown_slug_returns_not_found(tmp_path: Path):
    repo = _seed(tmp_path)

    out = handle_wiki_get(repo, slug="does-not-exist")

    assert out["found"] is False
    assert out["slug"] == "does-not-exist"
