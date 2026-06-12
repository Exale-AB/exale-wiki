"""Vector index rebuild/backfill from markdown (T06)."""

from pathlib import Path

from wiki_engine.page import Page
from wiki_engine.reindex import reindex
from wiki_engine.repo import WikiRepo
from wiki_engine.retrieval import InMemoryVectorStore


class StubEmbedder:
    def embed(self, texts):  # noqa: ANN001
        # Distinct deterministic vector per text length bucket — enough for search.
        return [[float(len(t)), 1.0] for t in texts]


def _repo(tmp_path: Path) -> WikiRepo:
    repo = WikiRepo.init(tmp_path, committer=lambda _r, _m: None)
    repo.write_page(Page(slug="one", frontmatter={"title": "One"}, body="first body"))
    repo.write_page(Page(slug="two", frontmatter={"title": "Two"}, body="second longer body"))
    return repo


def test_reindex_embeds_all_pages(tmp_path: Path):
    repo = _repo(tmp_path)
    store = InMemoryVectorStore()

    result = reindex(repo, StubEmbedder(), store)

    assert result.embedded == 2
    found = {h.slug for h in store.search([10.0, 1.0], k=10)}
    assert found == {"one", "two"}


def test_reindex_is_idempotent(tmp_path: Path):
    repo = _repo(tmp_path)
    store = InMemoryVectorStore()

    reindex(repo, StubEmbedder(), store)
    result = reindex(repo, StubEmbedder(), store)

    assert result.embedded == 2
    assert len({h.slug for h in store.search([10.0, 1.0], k=10)}) == 2
