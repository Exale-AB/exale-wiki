"""Tests for off-limits category enforcement in wiki ingest."""

from pathlib import Path

import pytest

from wiki_engine.errors import SchemaError
from wiki_engine.fakes import FakeSummarizer
from wiki_engine.ingest import ingest
from wiki_engine.repo import WikiRepo
from wiki_engine.schema import (
    WikiSchema,
    get_off_limits_categories,
    validate_ingestion_category,
)
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


def test_get_off_limits_categories():
    """Parse off-limits categories from schema."""
    schema = {"off_limits": ["confidential", "legal", "executive-only"]}
    off_limits = get_off_limits_categories(schema)
    assert off_limits == ["confidential", "legal", "executive-only"]


def test_get_off_limits_categories_empty():
    """Empty off_limits returns empty list."""
    schema = {}
    off_limits = get_off_limits_categories(schema)
    assert off_limits == []


def test_validate_ingestion_category_allowed():
    """Allowed category passes validation."""
    schema = {"off_limits": ["confidential"]}
    # Should not raise
    validate_ingestion_category("general", schema)


def test_validate_ingestion_category_off_limits():
    """Off-limits category raises SchemaError."""
    schema = {"off_limits": ["confidential", "legal"]}

    with pytest.raises(SchemaError, match="off-limits"):
        validate_ingestion_category("confidential", schema)


def test_ingest_rejects_off_limits_category(tmp_path: Path):
    """ingest rejects off-limits content via schema validation."""
    repo = _repo(tmp_path)

    # Try to ingest a page that would be marked as confidential
    # We'll test by having the default category be off-limits
    schema_with_off_limits_default = WikiSchema(
        default_category="confidential",
        honesty_rules={"off_limits": ["confidential"]},
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
        honesty_rules={"off_limits": ["confidential", "legal"]},
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
