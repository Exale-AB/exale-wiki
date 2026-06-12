"""Tests for off-limits category enforcement in wiki ingest.

T11 unified off-limits on the single canonical key
``honesty_rules.off_limits_categories``; the legacy top-level ``off_limits`` key
and its ``get_off_limits_categories`` / ``validate_ingestion_category`` helpers
were removed.
"""

from pathlib import Path

import pytest

from wiki_engine.errors import SchemaError
from wiki_engine.fakes import FakeSummarizer
from wiki_engine.ingest import ingest
from wiki_engine.repo import WikiRepo
from wiki_engine.schema import WikiSchema
from wiki_engine.source import Source, SourceKind


def _repo(tmp_path: Path) -> WikiRepo:
    """Create a test WikiRepo."""
    return WikiRepo.init(tmp_path, committer=lambda _root, _msg: None)


def _source(**kw) -> Source:
    """Create a test Source."""
    base = {
        "kind": SourceKind.MESSAGE,
        "identifier": "msg-1",
        "text": "Test content",
        "title": "Test Page",
    }
    base.update(kw)
    return Source(**base)


def test_ingest_rejects_off_limits_category(tmp_path: Path):
    """ingest rejects a page whose category is off-limits (canonical key)."""
    repo = _repo(tmp_path)

    schema_with_off_limits_default = WikiSchema(
        default_category="confidential",
        honesty_rules={"off_limits_categories": ["confidential"]},
    )

    with pytest.raises(SchemaError, match="off-limits"):
        ingest(
            _source(),
            repo=repo,
            schema=schema_with_off_limits_default,
            summarizer=FakeSummarizer(),
        )


def test_ingest_allows_permitted_category(tmp_path: Path):
    """ingest accepts permitted categories."""
    repo = _repo(tmp_path)

    schema = WikiSchema(
        default_category="general",
        honesty_rules={"off_limits_categories": ["confidential", "legal"]},
    )

    result = ingest(
        _source(),
        repo=repo,
        schema=schema,
        summarizer=FakeSummarizer(),
    )

    # Should succeed and create the page
    assert result.created is True
    assert result.slug == "test-page"

    page = repo.read_page("test-page")
    assert page is not None
    assert page.frontmatter["category"] == "general"
