---
default_category: General
page_types: [source, entity, concept, procedure, reference]
page_type_rules:
  procedure:
    required_frontmatter_fields: [type, category, author]
    allowed_categories: [Sales, Support, Ops]
    expected_section_headers: [Overview, Steps, Notes]
    expected_markers: []
  reference:
    required_frontmatter_fields: [type, category]
    allowed_categories: null
    expected_section_headers: []
    expected_markers: []
  entity:
    required_frontmatter_fields: [type]
    allowed_categories: null
    expected_section_headers: []
    expected_markers: []
  concept:
    required_frontmatter_fields: [type, category]
    allowed_categories: null
    expected_section_headers: []
    expected_markers: []
  source:
    required_frontmatter_fields: [type]
    allowed_categories: null
    expected_section_headers: []
    expected_markers: []
allowed_source_kinds: [email, slack, web_url, uploaded_file]
lint_thresholds:
  staleness_days: 60
  semantic_similarity_min: 0.2
  duplicate_similarity_max: 0.85
honesty_rules:
  require_source_for_claims: true
  confidence_threshold: 0.8
  off_limits_categories: [HIPAA, LEGAL]
---

# Schema / AGENTS.md

This is the per-seat rulebook that governs wiki structure and behavior.

## Page Type Specifications

### Procedure

A step-by-step guide with required author and category fields. Expected to include overview, detailed steps, and notes sections.

**Required frontmatter fields**: type, category, author
**Allowed categories**: Sales, Support, Ops
**Expected section headers**: Overview, Steps, Notes

### Reference

General reference material with minimal constraints.

**Required frontmatter fields**: type, category

### Entity

A discrete entity or object reference.

**Required frontmatter fields**: type

### Concept

A conceptual or theoretical entry.

**Required frontmatter fields**: type, category

### Source

A source document or raw material.

**Required frontmatter fields**: type

## Source Kind Constraints

Allowed source kinds for ingest:
- email
- slack
- web_url
- uploaded_file

## Lint Configuration

**Staleness threshold**: 60 days (sources older than 60 days are flagged)
**Semantic similarity minimum**: 0.2 (for duplicate detection)
**Duplicate similarity maximum**: 0.85 (threshold above which content is considered duplicate)

## Honesty Rules

- Require sources for claims
- Confidence threshold: 0.8
- Off-limits categories: HIPAA, LEGAL (cannot be used for ingest)
