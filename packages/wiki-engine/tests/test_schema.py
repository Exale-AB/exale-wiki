import pytest

from wiki_engine import SchemaError
from wiki_engine.schema import WikiSchema, parse_schema


def test_defaults_when_frontmatter_absent():
    schema = parse_schema("# Rulebook\n\nProse only, no frontmatter.\n")
    assert isinstance(schema, WikiSchema)
    assert schema.default_category == "General"
    assert schema.page_types == ("source", "entity", "concept")


def test_parses_frontmatter_rules():
    text = "---\ndefault_category: Accounts\npage_types: [source, entity]\n---\n\n# Rulebook\n"
    schema = parse_schema(text)
    assert schema.default_category == "Accounts"
    assert schema.page_types == ("source", "entity")


def test_rejects_non_string_default_category():
    with pytest.raises(SchemaError, match="default_category"):
        parse_schema("---\ndefault_category: 3\n---\n")


def test_rejects_non_string_page_types():
    with pytest.raises(SchemaError, match="page_types"):
        parse_schema("---\npage_types: [1, 2]\n---\n")


def test_parses_page_type_rules():
    """Schema parses per-type rules from frontmatter."""
    text = """---
default_category: Accounts
page_types: [source, entity, concept]
page_type_rules:
  source:
    required_frontmatter_fields: [type, category, author]
    allowed_categories: [Customer, Internal, External]
    expected_section_headers: [Summary, Metadata]
    expected_markers: []
  entity:
    required_frontmatter_fields: [type, category]
    allowed_categories: null
    expected_section_headers: []
    expected_markers: []
---

# Rulebook
"""
    schema = parse_schema(text)
    source_rule = schema.page_type_rules["source"]
    assert source_rule.required_frontmatter_fields == ("type", "category", "author")
    assert source_rule.allowed_categories == ("Customer", "Internal", "External")
    entity_rule = schema.page_type_rules["entity"]
    assert entity_rule.allowed_categories is None


def test_rejects_non_dict_page_type_rules():
    with pytest.raises(SchemaError, match="page_type_rules"):
        parse_schema("---\npage_type_rules: [1, 2]\n---\n")


@pytest.mark.unit
def test_parses_allowed_source_kinds():
    """Schema parses allowed source kinds."""
    text = """---
allowed_source_kinds: [email, slack, web_url]
---
"""
    schema = parse_schema(text)
    assert schema.allowed_source_kinds == ("email", "slack", "web_url")


@pytest.mark.unit
def test_parses_lint_thresholds():
    """Schema parses lint thresholds."""
    text = """---
lint_thresholds:
  staleness_days: 60
  semantic_similarity_min: 0.3
  duplicate_similarity_max: 0.9
---
"""
    schema = parse_schema(text)
    assert schema.lint_thresholds["staleness_days"] == 60
    assert schema.lint_thresholds["semantic_similarity_min"] == 0.3


@pytest.mark.unit
def test_parses_honesty_rules():
    """Schema parses honesty rules."""
    text = """---
honesty_rules:
  require_source_for_claims: true
  confidence_threshold: 0.8
  off_limits_categories: [HIPAA, Internal Legal]
---
"""
    schema = parse_schema(text)
    assert schema.honesty_rules["require_source_for_claims"] is True
    assert schema.honesty_rules["confidence_threshold"] == 0.8
    assert schema.honesty_rules["off_limits_categories"] == ["HIPAA", "Internal Legal"]
