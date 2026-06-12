"""Lint operations and self-improvement suggestions for the Knowledge Wiki."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable

if TYPE_CHECKING:
    from .knowledge_graph import WikiGraph
    from .protocols import Embedder
    from .repo import WikiRepo
    from .schema import WikiSchema

from .conflicts import detect_fact_contradictions
from .schema import get_lint_threshold
from .slug import slugify


@runtime_checkable
class LintRule(Protocol):
    """Interface that all lint rules must implement."""

    name: str

    def check(self, repo: WikiRepo, schema: WikiSchema) -> list[Violation]:
        """Run the rule; return all violations found."""
        ...


@dataclass
class Violation:
    """A structured finding from a lint rule."""

    rule: str
    # e.g., "orphaned_page", "contradiction", "stale_sources"

    severity: Literal["info", "warning", "error"]
    # info = minor concern; warning = should fix; error = critical

    confidence: float
    # 0–1, how certain we are this is actually a problem

    message: str
    # Human-readable explanation

    affected_pages: list[str]
    # Slug(s) involved

    suggested_action: str
    # Actionable category: "add_cross_link", "investigate_contradiction", etc.

    metadata: dict[str, Any]
    # Rule-specific context


@dataclass
class RefinementSuggestion:
    """A proposed change to schema/AGENTS.md."""

    violation_pattern: str
    # Descriptive pattern: "many orphaned_page violations of type Procedure"

    suggested_change: str
    # Description of the refinement

    confidence: float
    # (frequency of pattern) × (mean confidence of violations in pattern)

    examples: list[Violation]
    # Concrete violations that would be addressed by this refinement


def orphaned_page(repo: WikiRepo, schema: WikiSchema) -> list[Violation]:
    """Find pages with no inbound wikilinks."""
    violations: list[Violation] = []

    # Collect all inbound links by page slug
    inbound: dict[str, set[str]] = {}

    # Include index page in traversal
    pages_to_check = list(repo.list_pages())
    index_page = repo.read_page("index")
    if index_page:
        pages_to_check.insert(0, index_page)

    for page in pages_to_check:
        for wikilink in page.wikilinks:
            # Slugify wikilink text to match against page slugs
            target_slug = slugify(wikilink)
            if target_slug not in inbound:
                inbound[target_slug] = set()
            inbound[target_slug].add(page.slug)

    # Check for pages with no inbound links
    for page in pages_to_check:
        if page.slug not in inbound and page.slug != "index":
            # index.md is allowed to have no inbound links (it's the root)
            violations.append(
                Violation(
                    rule="orphaned_page",
                    severity="warning",
                    confidence=0.95,
                    message=f"Page '{page.slug}' has no inbound wikilinks",
                    affected_pages=[page.slug],
                    suggested_action="add_cross_link",
                    metadata={"page_type": page.frontmatter.get("type", "unknown")},
                )
            )

    return violations


def broken_wikilink(repo: WikiRepo, schema: WikiSchema) -> list[Violation]:
    """Find wikilinks that reference non-existent pages."""
    violations: list[Violation] = []

    # Collect all valid page slugs
    valid_pages = {page.slug for page in repo.list_pages()}

    # Also include index if it exists
    index_page = repo.read_page("index")
    if index_page:
        valid_pages.add(index_page.slug)

    # Check each page for broken links
    pages_to_check = list(repo.list_pages())
    if index_page:
        pages_to_check.insert(0, index_page)

    for page in pages_to_check:
        for wikilink in page.wikilinks:
            # Slugify wikilink text to match against page slugs
            target_slug = slugify(wikilink)
            if target_slug not in valid_pages:
                violations.append(
                    Violation(
                        rule="broken_wikilink",
                        severity="error",
                        confidence=0.99,
                        message=f"Page '{page.slug}' references non-existent page '[[{wikilink}]]'",
                        affected_pages=[page.slug],
                        suggested_action="fix_reference",
                        metadata={"target": wikilink},
                    )
                )

    return violations


def structural_contradiction(repo: WikiRepo, schema: WikiSchema) -> list[Violation]:
    """Find pages whose content doesn't match their declared type."""
    violations: list[Violation] = []

    # Include index page in traversal
    pages_to_check = list(repo.list_pages())
    index_page = repo.read_page("index")
    if index_page:
        pages_to_check.insert(0, index_page)

    for page in pages_to_check:
        page_type = page.frontmatter.get("type")
        if not isinstance(page_type, str) or page_type not in schema.page_type_rules:
            continue  # Skip pages without type rules defined

        type_rules = schema.page_type_rules[page_type]
        expected_markers = type_rules.expected_markers

        # Check if any expected marker appears in the content
        has_expected_marker = any(
            marker.lower() in page.body.lower() for marker in expected_markers
        )

        if expected_markers and not has_expected_marker:
            violations.append(
                Violation(
                    rule="structural_contradiction",
                    severity="warning",
                    confidence=0.85,
                    message=(
                        f"Page '{page.slug}' is type '{page_type}' but lacks "
                        f"expected markers: {expected_markers}"
                    ),
                    affected_pages=[page.slug],
                    suggested_action="fix_frontmatter",
                    metadata={
                        "declared_type": page_type,
                        "missing_markers": expected_markers,
                    },
                )
            )

    return violations


def semantic_contradiction(
    repo: WikiRepo, schema: WikiSchema, embedder: Embedder | None = None
) -> list[Violation]:
    """Find pages that make contradictory claims (via embeddings)."""
    violations: list[Violation] = []

    if embedder is None:
        # If no embedder provided, skip this rule (requires embedding capability)
        return violations

    # Include index page in traversal
    pages_to_check = list(repo.list_pages())
    index_page = repo.read_page("index")
    if index_page:
        pages_to_check.insert(0, index_page)

    # Compare each pair of pages for semantic contradiction
    for i, page_a in enumerate(pages_to_check):
        for page_b in pages_to_check[i + 1 :]:
            # Embed summaries of both pages (first 500 chars), batched
            embedding_a, embedding_b = embedder.embed([page_a.body[:500], page_b.body[:500]])

            # Calculate similarity (dot product)
            similarity = sum(a * b for a, b in zip(embedding_a, embedding_b, strict=False))

            # Low similarity can indicate contradiction
            # (This is heuristic; a more sophisticated check would use an LLM)
            if similarity < 0.2:  # Threshold for "very different"
                violations.append(
                    Violation(
                        rule="semantic_contradiction",
                        severity="info",
                        confidence=0.6,
                        message=(
                            f"Pages '{page_a.slug}' and '{page_b.slug}' may "
                            "contain contradictory claims"
                        ),
                        affected_pages=[page_a.slug, page_b.slug],
                        suggested_action="investigate_contradiction",
                        metadata={"similarity": float(similarity)},
                    )
                )

    return violations


def stale_sources(
    repo: WikiRepo, schema: WikiSchema, days_threshold: int | None = None
) -> list[Violation]:
    """Find pages built only from sources older than days_threshold.

    If days_threshold is None, reads from schema.lint_thresholds["staleness_days"],
    defaulting to 90 days if not present in schema.
    """
    violations: list[Violation] = []
    if days_threshold is None:
        days_threshold = int(get_lint_threshold(schema, "staleness_days", 90))
    cutoff = datetime.now() - timedelta(days=days_threshold)

    # Include index page in traversal
    pages_to_check = list(repo.list_pages())
    index_page = repo.read_page("index")
    if index_page:
        pages_to_check.insert(0, index_page)

    for page in pages_to_check:
        # Check if page has source metadata
        sources_list = page.frontmatter.get("sources", [])
        if not sources_list:
            continue  # Skip pages with no source metadata

        source_metadata = page.frontmatter.get("source_metadata", {})
        if not source_metadata:
            continue  # Skip pages with no source metadata

        # Check if all sources are older than threshold
        stale_sources_list = []
        all_stale = True
        max_age_days = 0

        for source_id in sources_list:
            source_info = source_metadata.get(source_id, {})
            ingested_at_str = source_info.get("ingested_at")
            if not ingested_at_str:
                all_stale = False  # Unknown date means we can't be sure it's stale
                break

            try:
                ingested_at = datetime.fromisoformat(ingested_at_str)
            except (ValueError, TypeError):
                all_stale = False  # Invalid date format means we can't be sure
                break

            if ingested_at >= cutoff:
                all_stale = False  # At least one source is recent
                break

            age_days = (datetime.now() - ingested_at).days
            max_age_days = max(max_age_days, age_days)
            stale_sources_list.append(source_id)

        if all_stale and stale_sources_list:
            violations.append(
                Violation(
                    rule="stale_sources",
                    severity="warning",
                    confidence=0.7,
                    message=(
                        f"Page '{page.slug}' built from sources >{days_threshold}d old "
                        f"(oldest: {max_age_days}d)"
                    ),
                    affected_pages=[page.slug],
                    suggested_action="refresh_sources",
                    metadata={
                        "age_days": max_age_days,
                        "threshold_days": days_threshold,
                    },
                )
            )

    return violations


def dead_source_urls(
    repo: WikiRepo, schema: WikiSchema, check_urls: bool = False, timeout: int = 5
) -> list[Violation]:
    """Find pages with dead/unreachable source URLs."""
    violations: list[Violation] = []

    if not check_urls:
        # Skip in unit tests (no network calls)
        return violations

    try:
        import requests
    except ImportError:
        # requests not available, skip this rule
        return violations

    # Include index page in traversal
    pages_to_check = list(repo.list_pages())
    index_page = repo.read_page("index")
    if index_page:
        pages_to_check.insert(0, index_page)

    for page in pages_to_check:
        source_metadata = page.frontmatter.get("source_metadata", {})
        if not source_metadata:
            continue

        for _source_id, source_info in source_metadata.items():
            if source_info.get("kind") != "url":
                continue

            url = source_info.get("location")
            if not url:
                continue

            try:
                response = requests.head(url, timeout=timeout, allow_redirects=True)
                if response.status_code >= 400:
                    violations.append(
                        Violation(
                            rule="dead_source_urls",
                            severity="warning",
                            confidence=0.8,
                            message=(
                                f"Source URL in '{page.slug}' returned "
                                f"{response.status_code}: {url}"
                            ),
                            affected_pages=[page.slug],
                            suggested_action="remove_source",
                            metadata={"url": url, "status_code": response.status_code},
                        )
                    )
            except Exception:
                # Any request error (timeout, connection, etc.)
                violations.append(
                    Violation(
                        rule="dead_source_urls",
                        severity="warning",
                        confidence=0.8,
                        message=f"Source URL in '{page.slug}' is unreachable: {url}",
                        affected_pages=[page.slug],
                        suggested_action="remove_source",
                        metadata={"url": url},
                    )
                )

    return violations


def duplicate_content(
    repo: WikiRepo,
    schema: WikiSchema,
    embedder: Embedder | None = None,
    threshold: float | None = None,
) -> list[Violation]:
    """Find pages with near-identical content.

    If threshold is None, reads from schema.lint_thresholds["duplicate_similarity_max"],
    defaulting to 0.8 if not present in schema.
    """
    violations: list[Violation] = []

    if embedder is None:
        return violations

    if threshold is None:
        threshold = get_lint_threshold(schema, "duplicate_similarity_max", 0.8)

    # Include index page in traversal
    pages_to_check = list(repo.list_pages())
    index_page = repo.read_page("index")
    if index_page:
        pages_to_check.insert(0, index_page)

    # Compare each pair of pages
    for i, page_a in enumerate(pages_to_check):
        for page_b in pages_to_check[i + 1 :]:
            # Embed page content, batched
            embedding_a, embedding_b = embedder.embed([page_a.body, page_b.body])

            # Calculate similarity (dot product)
            similarity = sum(a * b for a, b in zip(embedding_a, embedding_b, strict=False))

            if similarity > threshold:
                violations.append(
                    Violation(
                        rule="duplicate_content",
                        severity="warning",
                        confidence=0.75,
                        message=(
                            f"Pages '{page_a.slug}' and '{page_b.slug}' have "
                            f"{similarity:.1%} content overlap"
                        ),
                        affected_pages=[page_a.slug, page_b.slug],
                        suggested_action="merge_pages",
                        metadata={"similarity": float(similarity)},
                    )
                )

    return violations


def fact_contradiction(
    repo: WikiRepo,
    schema: WikiSchema,
    graph: WikiGraph | None = None,
) -> list[Violation]:
    """Find facts sharing (head, relation) with different tails via the knowledge graph."""
    if graph is None:
        return []

    conflicts = detect_fact_contradictions(graph)
    violations: list[Violation] = []
    for c in conflicts:
        violations.append(
            Violation(
                rule="fact_contradiction",
                severity="warning",
                confidence=0.9,
                message=(
                    f"Conflicting facts: ({c.fact_a.head}, {c.fact_a.relation}) → "
                    f"'{c.fact_a.tail}' vs '{c.fact_b.tail}'"
                ),
                affected_pages=[c.page_a, c.page_b],
                suggested_action="investigate_contradiction",
                metadata={
                    "fact_a": list(c.fact_a),
                    "fact_b": list(c.fact_b),
                    "conflict_type": c.conflict_type,
                },
            )
        )
    return violations


def lint(
    repo: WikiRepo,
    schema: WikiSchema,
    min_confidence: float = 0.7,
    rules: list[Callable[[WikiRepo, WikiSchema], list[Violation]]] | None = None,
    embedder: Embedder | None = None,
    graph: WikiGraph | None = None,
) -> list[Violation]:
    """Run all lint rules on the repo; return violations >= min_confidence.

    Default rules use schema-driven thresholds:
    - stale_sources reads staleness_days from schema
    - duplicate_content reads duplicate_similarity_max from schema
    """
    if rules is None:
        # Default: all built-in rules (as callables, not protocol objects)
        rules = [
            orphaned_page,
            broken_wikilink,
            structural_contradiction,
            lambda r, s: stale_sources(r, s, days_threshold=None),
            dead_source_urls,
        ]
        # Graph-based rules
        if graph:
            rules.append(lambda r, s: fact_contradiction(r, s, graph))
        # Include embedding-based rules only if embedder is provided
        if embedder:
            rules.extend(
                [
                    lambda r, s: semantic_contradiction(r, s, embedder),
                    lambda r, s: duplicate_content(r, s, embedder, threshold=None),
                ]
            )

    # Run all rules and aggregate violations
    all_violations: list[Violation] = []
    for rule in rules:
        # Call rule directly (all default rules are functions)
        all_violations.extend(rule(repo, schema))

    # Filter by confidence threshold
    filtered = [v for v in all_violations if v.confidence >= min_confidence]

    # Sort by severity (error > warning > info), then by confidence (descending)
    severity_order = {"error": 0, "warning": 1, "info": 2}
    filtered.sort(key=lambda v: (severity_order.get(v.severity, 3), -v.confidence))

    return filtered


def suggest_refinements(
    violations: list[Violation],
    repo: WikiRepo,
    min_pattern_frequency: float = 0.3,
) -> list[RefinementSuggestion]:
    """Analyze violations to suggest schema refinements."""
    if not violations:
        return []

    suggestions: list[RefinementSuggestion] = []

    # Group violations by rule + page type
    patterns: dict[tuple[str, str], list[Violation]] = {}
    for v in violations:
        page_type = "unknown"
        for slug in v.affected_pages:
            page = repo.read_page(slug)
            if page:
                page_type = page.frontmatter.get("type", "unknown")
                break

        key = (v.rule, page_type)
        if key not in patterns:
            patterns[key] = []
        patterns[key].append(v)

    # Analyze patterns for actionable refinements
    for (rule, page_type), rule_violations in patterns.items():
        frequency = len(rule_violations) / max(len(violations), 1)

        if frequency >= min_pattern_frequency and len(rule_violations) >= 2:
            # Generate a suggestion for this pattern
            if rule == "orphaned_page":
                suggestion = RefinementSuggestion(
                    violation_pattern=f"many orphaned_page violations of type {page_type}",
                    suggested_change=(
                        f"Add mandatory cross-reference rule to schema/AGENTS.md: "
                        f"'{page_type}' pages must link to at least one Index or Guide page."
                    ),
                    confidence=(
                        frequency
                        * sum(v.confidence for v in rule_violations)
                        / len(rule_violations)
                    ),
                    examples=rule_violations[:3],  # Show first 3 examples
                )
                suggestions.append(suggestion)

            elif rule == "stale_sources":
                suggestion = RefinementSuggestion(
                    violation_pattern="many stale_sources violations (sources >90 days old)",
                    suggested_change=(
                        "Reduce staleness threshold from 90 days to 60 days, or add "
                        "periodic source refresh checkpoints to schema/AGENTS.md."
                    ),
                    confidence=(
                        frequency
                        * sum(v.confidence for v in rule_violations)
                        / len(rule_violations)
                    ),
                    examples=rule_violations[:3],
                )
                suggestions.append(suggestion)

            elif rule == "structural_contradiction":
                missing_markers = set()
                for v in rule_violations:
                    missing_markers.update(v.metadata.get("missing_markers", []))

                suggestion = RefinementSuggestion(
                    violation_pattern=(
                        f"many structural_contradiction violations in type {page_type}"
                    ),
                    suggested_change=(
                        f"Update schema/AGENTS.md to enforce expected content "
                        f"markers for {page_type}: {list(missing_markers)}"
                    ),
                    confidence=(
                        frequency
                        * sum(v.confidence for v in rule_violations)
                        / len(rule_violations)
                    ),
                    examples=rule_violations[:3],
                )
                suggestions.append(suggestion)

    # Sort by confidence descending
    suggestions.sort(key=lambda s: -s.confidence)

    return suggestions
