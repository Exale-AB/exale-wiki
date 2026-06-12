"""Tests for schema enforcement functions."""

import pytest

from wiki_engine.page import Page
from wiki_engine.schema import (
    PageTypeRule,
    SchemaError,
    WikiSchema,
    enforce_honesty_category,
    enforce_page_category,
    enforce_page_type_frontmatter,
    enforce_source_kind,
    get_lint_threshold,
)


def test_enforce_page_type_requires_frontmatter_fields():
    """enforce_page_type_frontmatter validates required fields."""
    schema = WikiSchema(
        page_type_rules={
            "Runbook": PageTypeRule(required_frontmatter_fields=("type", "category", "author"))
        }
    )

    # Valid: has all required fields
    page_valid = Page(
        slug="test",
        frontmatter={"type": "Runbook", "category": "Ops", "author": "Jane"},
        body="content",
    )
    enforce_page_type_frontmatter(page_valid, schema)  # Should not raise

    # Invalid: missing 'author'
    page_invalid = Page(
        slug="test",
        frontmatter={"type": "Runbook", "category": "Ops"},
        body="content",
    )
    with pytest.raises(SchemaError, match="author"):
        enforce_page_type_frontmatter(page_invalid, schema)


def test_enforce_page_category_allowed():
    """enforce_page_category validates against allowed_categories."""
    schema = WikiSchema(
        page_type_rules={"Procedure": PageTypeRule(allowed_categories=("Sales", "Support"))}
    )

    # Valid: category is allowed
    page_valid = Page(
        slug="test", frontmatter={"type": "Procedure", "category": "Sales"}, body="content"
    )
    enforce_page_category(page_valid, schema)  # Should not raise

    # Invalid: category not in allowed list
    page_invalid = Page(
        slug="test", frontmatter={"type": "Procedure", "category": "Marketing"}, body="content"
    )
    with pytest.raises(SchemaError, match="not in allowed"):
        enforce_page_category(page_invalid, schema)


def test_enforce_source_kind_allowed():
    """enforce_source_kind validates source against allowed kinds."""
    schema = WikiSchema(allowed_source_kinds=("email", "web_url"))

    # Valid source kind
    enforce_source_kind("email", schema)  # Should not raise

    # Invalid source kind
    with pytest.raises(SchemaError, match="not allowed"):
        enforce_source_kind("slack", schema)


def test_enforce_honesty_off_limits_categories():
    """enforce_honesty checks off-limits categories."""
    schema = WikiSchema(honesty_rules={"off_limits_categories": ["HIPAA", "LEGAL"]})

    # Valid: allowed category
    page = Page(
        slug="test", frontmatter={"type": "Procedure", "category": "Support"}, body="content"
    )
    enforce_honesty_category(page, schema)  # Should not raise

    # Invalid: off-limits category
    page_restricted = Page(
        slug="test", frontmatter={"type": "Procedure", "category": "HIPAA"}, body="content"
    )
    with pytest.raises(SchemaError, match="off-limits"):
        enforce_honesty_category(page_restricted, schema)


def test_get_lint_threshold_from_schema():
    """get_lint_threshold returns schema value when present."""
    schema = WikiSchema(lint_thresholds={"staleness_days": 60})

    threshold = get_lint_threshold(schema, "staleness_days", 90)
    assert threshold == 60


def test_get_lint_threshold_uses_default():
    """get_lint_threshold returns default when key not in schema."""
    schema = WikiSchema(lint_thresholds={})

    threshold = get_lint_threshold(schema, "staleness_days", 90)
    assert threshold == 90


def test_enforce_page_type_skips_unknown_types():
    """enforce_page_type_frontmatter skips pages without type rules."""
    schema = WikiSchema(page_type_rules={})

    page = Page(slug="test", frontmatter={"type": "Unknown"}, body="content")
    enforce_page_type_frontmatter(page, schema)  # Should not raise


def test_enforce_page_category_skips_unconstrained_types():
    """enforce_page_category skips types without category constraints."""
    schema = WikiSchema(page_type_rules={"Procedure": PageTypeRule(allowed_categories=None)})

    page = Page(
        slug="test", frontmatter={"type": "Procedure", "category": "Unknown"}, body="content"
    )
    enforce_page_category(page, schema)  # Should not raise


def test_enforce_page_type_missing_multiple_fields():
    """enforce_page_type_frontmatter reports all missing fields."""
    schema = WikiSchema(
        page_type_rules={
            "Procedure": PageTypeRule(
                required_frontmatter_fields=("type", "category", "author", "date")
            )
        }
    )

    page = Page(slug="test", frontmatter={"type": "Procedure"}, body="content")
    with pytest.raises(SchemaError, match="category"):
        enforce_page_type_frontmatter(page, schema)


def test_enforce_honesty_empty_off_limits():
    """enforce_honesty with no off-limits categories allows all."""
    schema = WikiSchema(honesty_rules={})

    page = Page(
        slug="test", frontmatter={"type": "Procedure", "category": "AnyCategory"}, body="content"
    )
    enforce_honesty_category(page, schema)  # Should not raise
