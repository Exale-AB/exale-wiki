"""Integration tests: schema rules drive ingest and lint behavior."""

import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from wiki_engine.lint import lint
from wiki_engine.page import Page
from wiki_engine.repo import WikiRepo
from wiki_engine.schema import PageTypeRule, SchemaError, WikiSchema


def test_schema_page_type_rules_enforce_ingest_format():
    """Changing page type rules in schema changes ingest validation."""
    from wiki_engine.schema import enforce_page_type_frontmatter

    # Scenario: Strict schema requires 'author' field for all Runbooks
    strict_schema = WikiSchema(
        page_type_rules={
            "Runbook": PageTypeRule(required_frontmatter_fields=("type", "category", "author"))
        }
    )

    page_without_author = Page(
        slug="test",
        frontmatter={"type": "Runbook", "category": "Ops"},
        body="Test content",
    )

    # Should raise because 'author' is missing
    with pytest.raises(SchemaError, match="author"):
        enforce_page_type_frontmatter(page_without_author, strict_schema)

    # Scenario: Lenient schema doesn't require 'author'
    lenient_schema = WikiSchema(
        page_type_rules={"Runbook": PageTypeRule(required_frontmatter_fields=("type",))}
    )

    # Should not raise
    enforce_page_type_frontmatter(page_without_author, lenient_schema)


def test_schema_lint_thresholds_change_violations():
    """Changing lint_thresholds in schema changes which violations are reported."""
    # Create a test repo with pages having sources at different ages
    repo = WikiRepo.init(Path(tempfile.mkdtemp()))

    # Page with source 60 days old (stale for 30-day threshold, fresh for 90-day)
    old_date_60 = (datetime.now() - timedelta(days=60)).isoformat()
    repo.write_page(
        Page(
            slug="medium_age_page",
            frontmatter={
                "sources": ["src1"],
                "source_metadata": {"src1": {"ingested_at": old_date_60}},
            },
            body="Content from 60-day-old source",
        )
    )

    # Page with source 100 days old (stale for both thresholds)
    old_date_100 = (datetime.now() - timedelta(days=100)).isoformat()
    repo.write_page(
        Page(
            slug="very_old_page",
            frontmatter={
                "sources": ["src2"],
                "source_metadata": {"src2": {"ingested_at": old_date_100}},
            },
            body="Content from 100-day-old source",
        )
    )

    # Page with recent source (fresh for both thresholds)
    recent_date = datetime.now().isoformat()
    repo.write_page(
        Page(
            slug="recent_page",
            frontmatter={
                "sources": ["src3"],
                "source_metadata": {"src3": {"ingested_at": recent_date}},
            },
            body="Content from recent source",
        )
    )

    # Strict schema: 30-day staleness threshold
    strict_schema = WikiSchema(lint_thresholds={"staleness_days": 30})

    # Lenient schema: 90-day staleness threshold
    lenient_schema = WikiSchema(lint_thresholds={"staleness_days": 90})

    # Run lint with both schemas
    strict_violations = lint(repo, strict_schema, min_confidence=0.0)
    lenient_violations = lint(repo, lenient_schema, min_confidence=0.0)

    # Extract stale_sources violations
    strict_stale = [v for v in strict_violations if v.rule == "stale_sources"]
    lenient_stale = [v for v in lenient_violations if v.rule == "stale_sources"]

    # Strict threshold (30 days) should find more stale violations
    # Expected: both medium_age_page (60 days) and very_old_page (100 days)
    # Lenient threshold (90 days) should find fewer
    # Expected: only very_old_page (100 days)
    strict_len = len(strict_stale)
    lenient_len = len(lenient_stale)
    assert strict_len >= 2, (
        f"Expected >= 2 stale violations with 30-day threshold, got {strict_len}"
    )
    assert lenient_len >= 1, (
        f"Expected >= 1 stale violation with 90-day threshold, got {lenient_len}"
    )
    assert strict_len > lenient_len, (
        f"Strict schema should find more violations ({strict_len}) than lenient ({lenient_len})"
    )

    # Verify that both schemas correctly store their thresholds
    assert strict_schema.lint_thresholds["staleness_days"] == 30
    assert lenient_schema.lint_thresholds["staleness_days"] == 90


def test_schema_honesty_rules_prevent_off_limits_ingest():
    """Honesty rules prevent pages in off-limits categories."""
    from wiki_engine.schema import enforce_honesty_category

    schema = WikiSchema(honesty_rules={"off_limits_categories": ["HIPAA", "LEGAL", "TOP_SECRET"]})

    # Trying to create a HIPAA page raises
    page_restricted = Page(
        slug="medical_record",
        frontmatter={"type": "Runbook", "category": "HIPAA"},
        body="Patient info...",
    )

    with pytest.raises(SchemaError, match="off-limits"):
        enforce_honesty_category(page_restricted, schema)

    # Allowed category is fine
    page_allowed = Page(
        slug="sales_process",
        frontmatter={"type": "Runbook", "category": "Sales"},
        body="Sales process...",
    )

    enforce_honesty_category(page_allowed, schema)  # Should not raise


def test_schema_source_kinds_restrict_ingest():
    """Schema restricts which source kinds can be ingested."""
    from wiki_engine.schema import enforce_source_kind

    schema = WikiSchema(allowed_source_kinds=("email", "web_url", "uploaded_file"))

    # Allowed kinds
    enforce_source_kind("email", schema)
    enforce_source_kind("web_url", schema)

    # Disallowed kind
    with pytest.raises(SchemaError, match="not allowed"):
        enforce_source_kind("slack", schema)
