from pathlib import Path

import pytest

from wiki_engine import IngestError
from wiki_engine.errors import SchemaError
from wiki_engine.fakes import FakeSummarizer
from wiki_engine.ingest import IngestResult, ingest
from wiki_engine.log import parse_log
from wiki_engine.repo import WikiRepo
from wiki_engine.schema import PageTypeRule, WikiSchema
from wiki_engine.source import Source, SourceKind


def _repo(tmp_path: Path) -> WikiRepo:
    return WikiRepo.init(tmp_path, committer=lambda _root, _msg: None)


def _source(**kw) -> Source:
    base = {
        "kind": SourceKind.MESSAGE,
        "identifier": "msg-1",
        "text": "Acme renewed for Q3.\nDetails follow.",
        "title": "Acme Renewal",
    }
    base.update(kw)
    return Source(**base)


def test_ingest_creates_page_index_and_log(tmp_path: Path):
    repo = _repo(tmp_path)
    result = ingest(
        _source(),
        repo=repo,
        schema=WikiSchema(default_category="Accounts"),
        summarizer=FakeSummarizer(),
        date="2026-06-04",
    )
    assert result == IngestResult(slug="acme-renewal", created=True)

    page = repo.read_page("acme-renewal")
    assert page is not None
    assert page.frontmatter["title"] == "Acme Renewal"
    assert page.frontmatter["type"] == "source"
    assert "Acme renewed for Q3." in page.body

    assert "## Accounts" in repo.read_index()
    assert "[[Acme Renewal]] (acme-renewal)" in repo.read_index()

    log = parse_log(repo.read_log())
    assert log == [type(log[0])("2026-06-04", "ingest", "Acme Renewal")]


def test_ingest_stores_raw_copy_and_manifest(tmp_path: Path):
    repo = _repo(tmp_path)
    source = _source()
    ingest(repo=repo, source=source, schema=WikiSchema(), summarizer=FakeSummarizer())
    raw = repo.raw_dir / f"{source.identity()}.txt"
    assert raw.read_text(encoding="utf-8") == source.text
    assert (repo.raw_dir / "manifest.jsonl").read_text().count(source.identity()) == 1


def test_ingest_commits_once(tmp_path: Path):
    calls: list[str] = []
    repo = WikiRepo.init(tmp_path, committer=lambda _root, msg: calls.append(msg))
    ingest(_source(), repo=repo, schema=WikiSchema(), summarizer=FakeSummarizer())
    assert calls == ["ingest: Acme Renewal"]


def test_ingest_raises_on_empty_slug_title(tmp_path: Path):
    repo = _repo(tmp_path)
    with pytest.raises(IngestError, match="empty slug"):
        ingest(
            _source(title="!!!"),
            repo=repo,
            schema=WikiSchema(),
            summarizer=FakeSummarizer(),
        )


def test_reingest_same_title_new_identifier_accumulates_sources(tmp_path: Path):
    repo = _repo(tmp_path)
    ingest(_source(identifier="msg-1"), repo=repo, schema=WikiSchema(), summarizer=FakeSummarizer())
    ingest(
        _source(identifier="msg-2", text="Acme renewed bigger.\nMore."),
        repo=repo,
        schema=WikiSchema(),
        summarizer=FakeSummarizer(),
    )
    page = repo.read_page("acme-renewal")
    assert page is not None
    assert page.frontmatter["sources"] == ["msg-1", "msg-2"]
    assert len(repo.list_pages()) == 1


def test_reingest_same_identifier_changed_text_does_not_duplicate_source(tmp_path: Path):
    repo = _repo(tmp_path)
    ingest(_source(identifier="msg-1"), repo=repo, schema=WikiSchema(), summarizer=FakeSummarizer())
    ingest(
        _source(identifier="msg-1", text="completely different text body"),
        repo=repo,
        schema=WikiSchema(),
        summarizer=FakeSummarizer(),
    )
    page = repo.read_page("acme-renewal")
    assert page is not None
    assert page.frontmatter["sources"] == ["msg-1"]


def test_empty_summary_does_not_crash_catalog(tmp_path: Path):
    class _EmptySummarizer:
        def summarize(self, source: Source) -> str:
            return ""

    repo = _repo(tmp_path)
    result = ingest(_source(), repo=repo, schema=WikiSchema(), summarizer=_EmptySummarizer())
    assert result.created is True
    assert "(acme-renewal)" in repo.read_index()


def test_reingesting_identical_source_is_skipped(tmp_path: Path):
    repo = _repo(tmp_path)
    source = _source()
    first = ingest(source, repo=repo, schema=WikiSchema(), summarizer=FakeSummarizer())
    second = ingest(source, repo=repo, schema=WikiSchema(), summarizer=FakeSummarizer())

    assert first.created is True
    assert second == IngestResult(slug=None, skipped=True)
    # No duplicate page, no double-appended log, single manifest line.
    assert len(repo.list_pages()) == 1
    assert len(parse_log(repo.read_log())) == 1
    assert (repo.raw_dir / "manifest.jsonl").read_text().strip().count("\n") == 0


def test_changed_text_updates_same_page_without_duplicating(tmp_path: Path):
    repo = _repo(tmp_path)
    ingest(_source(), repo=repo, schema=WikiSchema(), summarizer=FakeSummarizer())
    updated = ingest(
        _source(text="Acme renewed AND expanded for Q3."),
        repo=repo,
        schema=WikiSchema(),
        summarizer=FakeSummarizer(),
    )
    assert updated.slug == "acme-renewal" and updated.updated is True
    assert len(repo.list_pages()) == 1  # same slug, updated in place
    assert "[[Acme Renewal]] (acme-renewal)" in repo.read_index()
    assert repo.read_index().count("(acme-renewal)") == 1  # catalog not duplicated


def test_off_limits_source_is_excluded_and_writes_nothing(tmp_path: Path):
    repo = _repo(tmp_path)
    result = ingest(
        _source(categories=("personal-finances",)),
        repo=repo,
        schema=WikiSchema(),
        summarizer=FakeSummarizer(),
        off_limits=["personal-finances", "legal-disputes"],
    )
    assert result == IngestResult(slug=None, excluded=True)
    assert repo.list_pages() == []
    assert parse_log(repo.read_log()) == []
    assert not (repo.raw_dir / "manifest.jsonl").exists()


def test_non_off_limits_categories_ingest_normally(tmp_path: Path):
    repo = _repo(tmp_path)
    result = ingest(
        _source(categories=("marketing",)),
        repo=repo,
        schema=WikiSchema(),
        summarizer=FakeSummarizer(),
        off_limits=["personal-finances"],
    )
    assert result.created is True and result.excluded is False


def test_ingest_embeds_and_upserts_when_store_and_embedder_given(tmp_path: Path):
    from wiki_engine.fakes import FakeEmbedder
    from wiki_engine.retrieval import InMemoryVectorStore

    repo = _repo(tmp_path)
    store = InMemoryVectorStore()
    embedder = FakeEmbedder(dim=32)
    ingest(
        _source(),
        repo=repo,
        schema=WikiSchema(),
        summarizer=FakeSummarizer(),
        embedder=embedder,
        store=store,
    )
    # The page was embedded and is retrievable by a query sharing its words.
    hits = store.search(embedder.embed(["Acme renewed for Q3"])[0], k=5)
    assert any(h.slug == "acme-renewal" for h in hits)


def test_ingest_without_store_does_not_require_embedder(tmp_path: Path):
    # Backwards-compatible: ingest still works with neither embedder nor store.
    repo = _repo(tmp_path)
    result = ingest(_source(), repo=repo, schema=WikiSchema(), summarizer=FakeSummarizer())
    assert result.created is True


def test_ingest_rejects_disallowed_source_kind(tmp_path: Path):
    repo = _repo(tmp_path)
    # Create a schema that does not allow MESSAGE kind
    schema = WikiSchema(allowed_source_kinds=("email", "slack", "web_url", "uploaded_file"))
    with pytest.raises(SchemaError, match="Source kind.*is not allowed"):
        ingest(
            _source(kind=SourceKind.MESSAGE),
            repo=repo,
            schema=schema,
            summarizer=FakeSummarizer(),
        )


def test_ingest_rejects_off_limits_honesty_category(tmp_path: Path):
    repo = _repo(tmp_path)
    # Create a schema where the default_category is in the off-limits list
    schema = WikiSchema(
        default_category="confidential",
        honesty_rules={"off_limits_categories": ["confidential"]},
    )
    with pytest.raises(SchemaError, match="is off-limits"):
        ingest(
            _source(),
            repo=repo,
            schema=schema,
            summarizer=FakeSummarizer(),
        )


# --- T11: schema enforces its full ruleset on ingest --------------------------


def test_ingest_enforces_page_type_required_frontmatter(tmp_path: Path):
    """Page-type required-frontmatter rules ARE enforced on ingest.

    Previously a silent gap: ingest never invoked page-type enforcement, so a
    seat's page_type_rules were decorative in the ingest path.
    """
    repo = _repo(tmp_path)
    schema = WikiSchema(
        page_type_rules={
            "source": PageTypeRule(required_frontmatter_fields=("type", "category", "author"))
        }
    )
    with pytest.raises(SchemaError, match="missing required frontmatter"):
        ingest(_source(), repo=repo, schema=schema, summarizer=FakeSummarizer())
    assert repo.list_pages() == []  # nothing persisted on rejection


def test_ingest_enforces_page_type_allowed_categories(tmp_path: Path):
    """A page-type that restricts categories is enforced on ingest."""
    repo = _repo(tmp_path)
    schema = WikiSchema(
        default_category="general",
        page_type_rules={"source": PageTypeRule(allowed_categories=("ops", "faq"))},
    )
    with pytest.raises(SchemaError, match="not in"):
        ingest(_source(), repo=repo, schema=schema, summarizer=FakeSummarizer())


def test_off_limits_excluded_does_not_summarize(tmp_path: Path):
    """An off-limits source is excluded BEFORE the (costly) summarize step."""
    repo = _repo(tmp_path)

    class _SpySummarizer:
        def __init__(self) -> None:
            self.called = False

        def summarize(self, source: Source) -> str:
            self.called = True
            return "should not happen"

    spy = _SpySummarizer()
    result = ingest(
        _source(categories=("personal-finances",)),
        repo=repo,
        schema=WikiSchema(),
        summarizer=spy,
        off_limits=["personal-finances"],
    )
    assert result == IngestResult(slug=None, excluded=True)
    assert spy.called is False


def test_ingest_legacy_off_limits_key_is_inert(tmp_path: Path):
    """Only honesty_rules.off_limits_categories gates ingest; the legacy
    'off_limits' key is no longer recognized (T11 single-key unification)."""
    repo = _repo(tmp_path)
    schema = WikiSchema(
        default_category="confidential",
        honesty_rules={"off_limits": ["confidential"]},  # legacy key → inert
    )
    result = ingest(_source(), repo=repo, schema=schema, summarizer=FakeSummarizer())
    assert result.created is True
