"""Minimal per-seat rulebook (schema/AGENTS.md) parsing for P4a.

Structured rules live in the file's YAML frontmatter; the prose below is human
guidance. P4d extends this with formatting/threshold/honesty enforcement.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .errors import SchemaError
from .page import parse_page

if TYPE_CHECKING:
    from .page import Page
    from .source import Source

__all__ = [
    "WikiSchema",
    "PageTypeRule",
    "parse_schema",
    "enforce_page_type_frontmatter",
    "enforce_page_category",
    "enforce_source_kind",
    "enforce_honesty_category",
    "get_lint_threshold",
]

_DEFAULT_PAGE_TYPES = ("source", "entity", "concept")


@dataclass(frozen=True)
class PageTypeRule:
    """Formatting rules for a specific page type."""

    required_frontmatter_fields: tuple[str, ...] = ("type", "category")
    allowed_categories: tuple[str, ...] | None = None
    expected_section_headers: tuple[str, ...] = ()
    expected_markers: tuple[str, ...] = ()
    max_stale_days: int | None = None


@dataclass(frozen=True)
class WikiSchema:
    default_category: str = "General"
    page_types: tuple[str, ...] = field(default=_DEFAULT_PAGE_TYPES)
    page_type_rules: Mapping[str, PageTypeRule] = field(default_factory=dict)
    allowed_source_kinds: tuple[str, ...] = (
        "email",
        "slack",
        "web_url",
        "uploaded_file",
        "message",
    )
    index_update_triggers: tuple[str, ...] = ("on_ingest",)
    log_append_triggers: tuple[str, ...] = ("on_ingest", "on_lint_violation")
    lint_thresholds: Mapping[str, float | int] = field(default_factory=dict)
    honesty_rules: Mapping[str, Any] = field(default_factory=dict)
    verbatim_categories: tuple[str, ...] = ("document",)

    @property
    def off_limits_categories(self) -> tuple[str, ...]:
        """Categories that may never be ingested for this seat.

        The single canonical source of truth for off-limits: the
        ``honesty_rules.off_limits_categories`` key. No other key is recognized.
        """
        return tuple(self.honesty_rules.get("off_limits_categories", ()))

    def enforce_source(self, source: Source) -> None:
        """Validate a source against the rulebook before ingest does any work.

        Currently the source-kind allow-list. Off-limits *categories* are handled
        as a soft exclusion (skip, don't raise) by ``ingest`` so the page is never
        written; raising here would change that contract.
        """
        enforce_source_kind(str(source.kind), self)

    def enforce_page(self, page: Page) -> None:
        """Run the full page ruleset in one defined order, before persisting.

        type-frontmatter -> category allow-list -> honesty (off-limits). Each step
        raises ``SchemaError`` on the first violation. This is the single entry
        point callers should use; the underlying ``enforce_*`` functions remain
        public for targeted use and testing.
        """
        enforce_page_type_frontmatter(page, self)
        enforce_page_category(page, self)
        enforce_honesty_category(page, self)


def parse_schema(text: str) -> WikiSchema:
    frontmatter = parse_page("AGENTS", text).frontmatter

    default_category = frontmatter.get("default_category", "General")
    if not isinstance(default_category, str):
        raise SchemaError("default_category must be a string")

    page_types = frontmatter.get("page_types", list(_DEFAULT_PAGE_TYPES))
    if not isinstance(page_types, list) or not all(isinstance(t, str) for t in page_types):
        raise SchemaError("page_types must be a list of strings")

    # Parse page_type_rules
    page_type_rules_raw = frontmatter.get("page_type_rules", {})
    if not isinstance(page_type_rules_raw, dict):
        raise SchemaError("page_type_rules must be a dict")

    page_type_rules = {}
    for ptype, rules_dict in page_type_rules_raw.items():
        if not isinstance(rules_dict, dict):
            raise SchemaError(f"page_type_rules[{ptype}] must be a dict")

        max_stale_days = rules_dict.get("max_stale_days")
        if max_stale_days is not None and not isinstance(max_stale_days, int):
            raise SchemaError(f"page_type_rules[{ptype}].max_stale_days must be int or null")

        page_type_rules[ptype] = PageTypeRule(
            required_frontmatter_fields=tuple(
                rules_dict.get("required_frontmatter_fields", ("type", "category"))
            ),
            allowed_categories=(
                tuple(rules_dict["allowed_categories"])
                if rules_dict.get("allowed_categories") is not None
                else None
            ),
            expected_section_headers=tuple(rules_dict.get("expected_section_headers", ())),
            expected_markers=tuple(rules_dict.get("expected_markers", ())),
            max_stale_days=max_stale_days,
        )

    # Parse allowed_source_kinds
    allowed_source_kinds = frontmatter.get(
        "allowed_source_kinds",
        ["email", "slack", "web_url", "uploaded_file", "message"],
    )
    if not isinstance(allowed_source_kinds, list) or not all(
        isinstance(k, str) for k in allowed_source_kinds
    ):
        raise SchemaError("allowed_source_kinds must be a list of strings")

    # Parse index_update_triggers
    index_update_triggers = frontmatter.get("index_update_triggers", ["on_ingest"])
    if not isinstance(index_update_triggers, list) or not all(
        isinstance(t, str) for t in index_update_triggers
    ):
        raise SchemaError("index_update_triggers must be a list of strings")

    # Parse log_append_triggers
    log_append_triggers = frontmatter.get("log_append_triggers", ["on_ingest", "on_lint_violation"])
    if not isinstance(log_append_triggers, list) or not all(
        isinstance(t, str) for t in log_append_triggers
    ):
        raise SchemaError("log_append_triggers must be a list of strings")

    # Parse lint_thresholds
    lint_thresholds = frontmatter.get("lint_thresholds", {})
    if not isinstance(lint_thresholds, dict):
        raise SchemaError("lint_thresholds must be a dict")
    for key, val in lint_thresholds.items():
        if not isinstance(val, (int, float)):
            raise SchemaError(f"lint_thresholds[{key}] must be a number")

    # Parse honesty_rules
    honesty_rules = frontmatter.get("honesty_rules", {})
    if not isinstance(honesty_rules, dict):
        raise SchemaError("honesty_rules must be a dict")

    # Parse verbatim_categories — categories whose sources are stored in full
    # (no summarization), so documents like CVs remain matchable verbatim.
    verbatim_categories = frontmatter.get("verbatim_categories", ["document"])
    if not isinstance(verbatim_categories, list) or not all(
        isinstance(c, str) for c in verbatim_categories
    ):
        raise SchemaError("verbatim_categories must be a list of strings")

    return WikiSchema(
        default_category=default_category,
        page_types=tuple(page_types),
        page_type_rules=page_type_rules,
        allowed_source_kinds=tuple(allowed_source_kinds),
        index_update_triggers=tuple(index_update_triggers),
        log_append_triggers=tuple(log_append_triggers),
        lint_thresholds=lint_thresholds,
        honesty_rules=honesty_rules,
        verbatim_categories=tuple(verbatim_categories),
    )


def enforce_page_type_frontmatter(page: Page, schema: WikiSchema) -> None:
    """Validate page frontmatter against its type's rules.

    Raises SchemaError if required fields are missing.
    """
    page_type = page.frontmatter.get("type")
    if not isinstance(page_type, str) or page_type not in schema.page_type_rules:
        return  # No rules defined for this type, skip

    rules = schema.page_type_rules[page_type]
    missing = []
    for field_name in rules.required_frontmatter_fields:
        if field_name not in page.frontmatter:
            missing.append(field_name)

    if missing:
        raise SchemaError(
            f"Page '{page.slug}' type '{page_type}' missing required frontmatter: {missing}"
        )


def enforce_page_category(page: Page, schema: WikiSchema) -> None:
    """Validate page category against allowed categories for its type.

    Raises SchemaError if category is not in the allowed list.
    """
    page_type = page.frontmatter.get("type")
    if not isinstance(page_type, str) or page_type not in schema.page_type_rules:
        return  # No rules defined for this type, skip

    rules = schema.page_type_rules[page_type]
    if rules.allowed_categories is None:
        return  # No category restrictions

    category = page.frontmatter.get("category")
    if category not in rules.allowed_categories:
        msg = (
            f"Page '{page.slug}' category '{category}' is not in "
            f"allowed: {rules.allowed_categories}"
        )
        raise SchemaError(msg)


def enforce_source_kind(source_kind: str, schema: WikiSchema) -> None:
    """Validate source kind against allowed source kinds.

    Raises SchemaError if source kind is not allowed.
    """
    if source_kind not in schema.allowed_source_kinds:
        raise SchemaError(
            f"Source kind '{source_kind}' is not allowed; allowed: {schema.allowed_source_kinds}"
        )


def enforce_honesty_category(page: Page, schema: WikiSchema) -> None:
    """Validate page category against off-limits categories.

    Raises SchemaError if category is in the off-limits list.
    """
    off_limits = schema.off_limits_categories
    category = page.frontmatter.get("category")
    # None category is never off-limits
    if category is None:
        return

    if category in off_limits:
        raise SchemaError(
            f"Page '{page.slug}' category '{category}' is off-limits: {list(off_limits)}"
        )


def get_lint_threshold(
    schema: WikiSchema, threshold_name: str, default: float | int
) -> float | int:
    """Get a lint threshold from schema, or use the default."""
    return schema.lint_thresholds.get(threshold_name, default)
