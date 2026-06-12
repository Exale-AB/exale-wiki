"""Provenance capture + visible degradation in MCP responses (T10)."""

from pathlib import Path

from wiki_engine.fakes import FakeAnswerer, FakeEmbedder, FakeSummarizer
from wiki_engine.llm_backends import HermesAnswerer, HermesSummarizer
from wiki_engine.mcp_server import handle_wiki_ingest, handle_wiki_query
from wiki_engine.page import Page
from wiki_engine.repo import WikiRepo
from wiki_engine.retrieval import NullVectorStore


class _StubClient:
    def complete(self, system, user, *, max_tokens):  # noqa: ANN001
        return "stub model output"


def _repo(tmp_path: Path) -> WikiRepo:
    repo = WikiRepo.init(tmp_path, committer=lambda _r, _m: None)
    repo.write_page(Page(slug="p", frontmatter={"title": "P"}, body="alpha"))
    repo.write_index("# Index\n\n## X\n- [[P]] (p) — alpha\n")
    return repo


def test_ingest_records_contributor_in_frontmatter(tmp_path: Path):
    repo = WikiRepo.init(tmp_path, committer=lambda _r, _m: None)

    result = handle_wiki_ingest(
        repo,
        source_text="A note from a bundle.",
        source_url=None,
        category="note",
        contributor="inbox-triage",
    )

    page = repo.read_page(result["slug"])
    assert page is not None
    assert page.frontmatter.get("contributor") == "inbox-triage"


def test_ingest_reports_fake_vs_model_mode(tmp_path: Path):
    repo = WikiRepo.init(tmp_path, committer=lambda _r, _m: None)

    fake = handle_wiki_ingest(
        repo, source_text="x one", source_url=None, category="n", summarizer=FakeSummarizer()
    )
    model = handle_wiki_ingest(
        repo,
        source_text="y two",
        source_url=None,
        category="n",
        summarizer=HermesSummarizer(_StubClient()),
    )

    assert fake["mode"] == "fake"
    assert model["mode"] == "model"


def test_query_flags_degraded_with_fake_answerer(tmp_path: Path):
    repo = _repo(tmp_path)

    resp = handle_wiki_query(
        repo,
        query="alpha",
        file_as_new_page=False,
        vectorstore=NullVectorStore(),
        embedder=FakeEmbedder(),
        answerer=FakeAnswerer(),
    )

    assert resp["mode"] == "fake"
    assert resp["degraded"] is True


def test_query_not_degraded_with_model_answerer(tmp_path: Path):
    repo = _repo(tmp_path)

    resp = handle_wiki_query(
        repo,
        query="alpha",
        file_as_new_page=False,
        vectorstore=NullVectorStore(),
        embedder=FakeEmbedder(),
        answerer=HermesAnswerer(_StubClient()),
    )

    assert resp["mode"] == "model"
    assert resp["degraded"] is False
