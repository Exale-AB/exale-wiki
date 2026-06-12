from pathlib import Path

from wiki_engine.fakes import FakeEmbedder
from wiki_engine.page import Page
from wiki_engine.repo import WikiRepo
from wiki_engine.retrieval import InMemoryVectorStore, Retriever


def _repo(tmp_path: Path) -> WikiRepo:
    return WikiRepo.init(tmp_path, committer=lambda _r, _m: None)


def _seed(repo: WikiRepo) -> None:
    # Two catalog entries; the "acme" page wikilinks to "Anna Lindqvist".
    repo.write_page(
        Page(
            slug="acme-ab",
            frontmatter={"title": "Acme AB"},
            body="Renewal contract with [[Anna Lindqvist]].",
        )
    )
    repo.write_page(
        Page(slug="anna-lindqvist", frontmatter={"title": "Anna Lindqvist"}, body="Marknadschef.")
    )
    index = (
        "# Index\n\n"
        "## Accounts\n"
        "- [[Acme AB]] (acme-ab) — Renewal contract overview\n"
        "## People\n"
        "- [[Anna Lindqvist]] (anna-lindqvist) — Contact at Acme\n"
    )
    repo.write_index(index)


def _retriever(repo: WikiRepo) -> Retriever:
    return Retriever(repo=repo, store=InMemoryVectorStore(), embedder=FakeEmbedder())


def test_structural_match_on_catalog_title_or_summary(tmp_path: Path):
    repo = _repo(tmp_path)
    _seed(repo)
    hits = _retriever(repo).structural("renewal contract", k=5)
    assert hits[0] == "acme-ab"


def test_structural_expands_to_wikilink_neighbors(tmp_path: Path):
    repo = _repo(tmp_path)
    _seed(repo)
    # "renewal" matches only the acme page's summary; anna is pulled in as a
    # wikilink neighbor of acme.
    hits = _retriever(repo).structural("renewal", k=5)
    assert "acme-ab" in hits
    assert "anna-lindqvist" in hits
    assert hits.index("acme-ab") < hits.index("anna-lindqvist")  # neighbor ranks after


def test_structural_no_match_returns_empty(tmp_path: Path):
    repo = _repo(tmp_path)
    _seed(repo)
    assert _retriever(repo).structural("kubernetes", k=5) == []
