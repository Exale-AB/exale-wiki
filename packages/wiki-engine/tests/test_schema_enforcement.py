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


def test_off_limits_categories_reads_canonical_key_only():
    """WikiSchema.off_limits_categories reads off_limits_categories only."""
    canonical = WikiSchema(honesty_rules={"off_limits_categories": ["a", "b"]})
    assert canonical.off_limits_categories == ("a", "b")
    # The legacy top-level 'off_limits' key is no longer recognized.
    assert WikiSchema(honesty_rules={"off_limits": ["a"]}).off_limits_categories == ()
    assert WikiSchema().off_limits_categories == ()


def test_schema_enforce_page_runs_full_ruleset():
    """schema.enforce_page is the single entry point: type + category + honesty."""
    # honesty violation surfaces through the one call
    honesty = WikiSchema(honesty_rules={"off_limits_categories": ["secret"]})
    page = Page(slug="p", frontmatter={"type": "source", "category": "secret"}, body="x")
    with pytest.raises(SchemaError, match="off-limits"):
        honesty.enforce_page(page)

    # required-frontmatter violation surfaces through the same call
    typed = WikiSchema(
        page_type_rules={"source": PageTypeRule(required_frontmatter_fields=("type", "author"))}
    )
    page2 = Page(slug="p", frontmatter={"type": "source", "category": "general"}, body="x")
    with pytest.raises(SchemaError, match="missing required frontmatter"):
        typed.enforce_page(page2)


def test_schema_enforce_source_checks_source_kind():
    """schema.enforce_source rejects a disallowed source kind."""
    from wiki_engine.source import Source, SourceKind

    schema = WikiSchema(allowed_source_kinds=("email",))
    src = Source(kind=SourceKind.MESSAGE, identifier="m", text="t", title="T")
    with pytest.raises(SchemaError, match="is not allowed"):
        schema.enforce_source(src)


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
