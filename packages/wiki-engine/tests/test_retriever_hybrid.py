from pathlib import Path

from wiki_engine.fakes import FakeEmbedder
from wiki_engine.page import Page
from wiki_engine.repo import WikiRepo
from wiki_engine.retrieval import InMemoryVectorStore, Retriever


def _repo(tmp_path: Path) -> WikiRepo:
    return WikiRepo.init(tmp_path, committer=lambda _r, _m: None)


def _build(tmp_path: Path) -> Retriever:
    repo = _repo(tmp_path)
    # "ops" page: its body mentions kubernetes, but the index summary does NOT,
    # so kubernetes is reachable only by vector recall.
    repo.write_page(
        Page(
            slug="ops-runbook",
            frontmatter={"title": "Ops Runbook"},
            body="kubernetes deployment steps",
        )
    )
    repo.write_page(
        Page(
            slug="acme-ab",
            frontmatter={"title": "Acme AB"},
            body="renewal contract terms",
        )
    )
    repo.write_index(
        "# Index\n\n"
        "## General\n"
        "- [[Ops Runbook]] (ops-runbook) — internal procedures\n"
        "- [[Acme AB]] (acme-ab) — renewal contract overview\n"
    )
    embedder = FakeEmbedder(dim=64)
    store = InMemoryVectorStore()
    # Embed page bodies into the store (as ingest will do in Task 8).
    for slug, body in (
        ("ops-runbook", "kubernetes deployment steps"),
        ("acme-ab", "renewal contract terms"),
    ):
        store.upsert(slug, embedder.embed([body])[0])
    return Retriever(repo=repo, store=store, embedder=embedder)


def test_structural_hit_ranks_first(tmp_path: Path):
    retriever = _build(tmp_path)
    hits = retriever.retrieve("renewal contract", k=5)
    assert hits[0] == "acme-ab"


def test_vector_only_term_is_recalled_when_structural_misses(tmp_path: Path):
    retriever = _build(tmp_path)
    # "kubernetes" appears in no index title/summary → structural misses;
    # vector recall finds ops-runbook via its embedded body.
    hits = retriever.retrieve("kubernetes", k=5)
    assert "ops-runbook" in hits


def test_retrieve_dedups_and_respects_k(tmp_path: Path):
    retriever = _build(tmp_path)
    hits = retriever.retrieve("renewal contract kubernetes", k=1)
    assert len(hits) == 1
    assert hits[0] == "acme-ab"  # structural beats vector for the top slot


def test_retrieve_empty_when_nothing_matches(tmp_path: Path):
    repo = _repo(tmp_path)
    repo.write_index("# Index\n")
    retriever = Retriever(repo=repo, store=InMemoryVectorStore(), embedder=FakeEmbedder())
    assert retriever.retrieve("anything", k=5) == []
