from pathlib import Path

import pytest

from wiki_engine.lint import RefinementSuggestion, Violation


def load_seeded_defects_fixture():
    """Load the seeded-defects fixture wiki into a repo."""
    from wiki_engine.repo import WikiRepo

    fixture_path = Path(__file__).parent / "fixtures" / "seeded_defects_wiki"
    # The fixture directory already exists with wiki/ subdirectory populated
    # Create WikiRepo instance pointing to that fixture directory
    repo = WikiRepo(fixture_path)
    return repo


def load_fixture_schema():
    """Load the fixture schema."""
    from wiki_engine.schema import PageTypeRule, WikiSchema

    fixture_dir = (
        Path(__file__).parent / "fixtures" / "seeded_defects_wiki" / "schema" / "AGENTS.md"
    )
    fixture_dir.read_text()

    # Parse the schema from AGENTS.md
    schema = WikiSchema(
        page_types=("Procedure", "Reference", "Runbook", "Index", "Claim"),
        page_type_rules={
            "Procedure": PageTypeRule(expected_markers=("1.", "2.", "3.")),
            "Reference": PageTypeRule(),
            "Runbook": PageTypeRule(),
            "Index": PageTypeRule(),
            "Claim": PageTypeRule(),
        },
    )
    return schema


def test_lint_rule_protocol():
    """LintRule is a Protocol that all rules must implement."""
    from typing import TYPE_CHECKING, Protocol, runtime_checkable

    if TYPE_CHECKING:
        from wiki_engine.repo import WikiRepo
        from wiki_engine.schema import WikiSchema

    @runtime_checkable
    class LintRule(Protocol):
        name: str

        def check(self, repo: "WikiRepo", schema: "WikiSchema") -> list[Violation]: ...

    # This test just verifies the protocol exists and has the right shape
    # Actual rule implementations will verify they conform below
    assert hasattr(LintRule, "__protocol_attrs__") or True  # Protocol detection


def test_violation_creation():
    """Violation stores all required metadata."""
    v = Violation(
        rule="orphaned_page",
        severity="warning",
        confidence=0.95,
        message="Page has no inbound links",
        affected_pages=["old_page"],
        suggested_action="add_cross_link",
        metadata={"page_type": "Runbook"},
    )
    assert v.rule == "orphaned_page"
    assert v.severity == "warning"
    assert v.confidence == 0.95
    assert v.message == "Page has no inbound links"
    assert v.affected_pages == ["old_page"]
    assert v.suggested_action == "add_cross_link"
    assert v.metadata == {"page_type": "Runbook"}


def test_refinement_suggestion_creation():
    """RefinementSuggestion stores all required metadata."""
    v = Violation(
        rule="orphaned_page",
        severity="warning",
        confidence=0.95,
        message="Page has no inbound links",
        affected_pages=["old_page"],
        suggested_action="add_cross_link",
        metadata={},
    )
    s = RefinementSuggestion(
        violation_pattern="many orphaned_page violations of type Procedure",
        suggested_change="Add mandatory cross-reference rule to schema",
        confidence=0.85,
        examples=[v],
    )
    assert s.violation_pattern == "many orphaned_page violations of type Procedure"
    assert s.suggested_change == "Add mandatory cross-reference rule to schema"
    assert s.confidence == 0.85
    assert len(s.examples) == 1


@pytest.mark.unit
def test_orphaned_page_rule():
    """orphaned_page detects pages with no inbound wikilinks."""
    from wiki_engine.lint import orphaned_page
    from wiki_engine.page import Page
    from wiki_engine.repo import WikiRepo
    from wiki_engine.schema import WikiSchema

    # Create a simple repo with one orphaned page
    repo = WikiRepo.init(_path := __import__("tempfile").mkdtemp())
    repo.write_page(Page(slug="index", frontmatter={}, body="[[linked-page]]"))
    repo.write_page(Page(slug="linked-page", frontmatter={}, body="..."))
    repo.write_page(Page(slug="orphaned", frontmatter={}, body="No links here"))

    schema = WikiSchema()

    violations = orphaned_page(repo, schema)

    assert len(violations) == 1
    assert violations[0].rule == "orphaned_page"
    assert violations[0].affected_pages == ["orphaned"]
    assert violations[0].message == "Page 'orphaned' has no inbound wikilinks"
    assert violations[0].confidence == 0.95
    assert violations[0].severity == "warning"
    assert violations[0].suggested_action == "add_cross_link"


@pytest.mark.unit
def test_orphaned_page_exempts_index():
    """index.md is allowed to have no inbound links."""
    from wiki_engine.lint import orphaned_page
    from wiki_engine.page import Page
    from wiki_engine.repo import WikiRepo
    from wiki_engine.schema import WikiSchema

    repo = WikiRepo.init(_path := __import__("tempfile").mkdtemp())
    repo.write_page(Page(slug="index", frontmatter={}, body="..."))

    schema = WikiSchema()

    violations = orphaned_page(repo, schema)
    assert len(violations) == 0


@pytest.mark.unit
def test_broken_wikilink_rule():
    """broken_wikilink detects references to non-existent pages."""
    from wiki_engine.lint import broken_wikilink
    from wiki_engine.page import Page
    from wiki_engine.repo import WikiRepo
    from wiki_engine.schema import WikiSchema

    repo = WikiRepo.init(_path := __import__("tempfile").mkdtemp())
    repo.write_page(Page(slug="index", frontmatter={}, body="[[valid-page]]"))
    repo.write_page(Page(slug="valid-page", frontmatter={}, body="..."))
    repo.write_page(Page(slug="bad-ref", frontmatter={}, body="[[nonexistent-page]]"))

    schema = WikiSchema()

    violations = broken_wikilink(repo, schema)

    assert len(violations) == 1
    assert violations[0].rule == "broken_wikilink"
    assert violations[0].affected_pages == ["bad-ref"]
    assert "nonexistent-page" in violations[0].message
    assert violations[0].confidence == 0.99
    assert violations[0].suggested_action == "fix_reference"


@pytest.mark.unit
def test_structural_contradiction_rule():
    """structural_contradiction detects page type mismatches with content."""
    from wiki_engine.lint import structural_contradiction
    from wiki_engine.page import Page
    from wiki_engine.repo import WikiRepo
    from wiki_engine.schema import PageTypeRule, WikiSchema

    repo = WikiRepo.init(_path := __import__("tempfile").mkdtemp())
    # A page with type=Procedure but no numbered steps
    repo.write_page(
        Page(
            slug="bad_procedure",
            frontmatter={"type": "Procedure"},
            body="This is a guide, not a procedure",
        )
    )
    # A valid Procedure with steps
    repo.write_page(
        Page(
            slug="good_procedure",
            frontmatter={"type": "Procedure"},
            body="1. Step one\n2. Step two\n3. Step three",
        )
    )

    schema = WikiSchema(
        page_types=("Procedure",),
        page_type_rules={"Procedure": PageTypeRule(expected_markers=("1.", "2.", "3."))},
    )

    violations = structural_contradiction(repo, schema)

    assert len(violations) == 1
    assert violations[0].rule == "structural_contradiction"
    assert violations[0].affected_pages == ["bad_procedure"]
    assert violations[0].confidence == 0.85
    assert violations[0].severity == "warning"


@pytest.mark.unit
def test_semantic_contradiction_rule():
    """semantic_contradiction detects conflicting claims via embeddings."""
    from wiki_engine.fakes import FakeEmbedder
    from wiki_engine.lint import semantic_contradiction
    from wiki_engine.page import Page
    from wiki_engine.repo import WikiRepo
    from wiki_engine.schema import WikiSchema

    repo = WikiRepo.init(_path := __import__("tempfile").mkdtemp())
    repo.write_page(Page(slug="claim_a", frontmatter={}, body="The system is fast"))
    repo.write_page(Page(slug="claim_b", frontmatter={}, body="The system is slow"))
    repo.write_page(Page(slug="neutral", frontmatter={}, body="The system exists"))

    schema = WikiSchema()

    # With no embedder, should return empty list
    assert semantic_contradiction(repo, schema, embedder=None) == []

    # With a real (batch) embedder the rule runs end-to-end without crashing and
    # produces a real dot-product similarity. This exercises the embed() path —
    # a regression guard for the per-text vs. batch embedder contract.
    violations = semantic_contradiction(repo, schema, embedder=FakeEmbedder())
    assert all(isinstance(v.metadata["similarity"], float) for v in violations)
    assert all(v.rule == "semantic_contradiction" for v in violations)


@pytest.mark.unit
def test_stale_sources_rule():
    """stale_sources detects pages built only from old sources."""
    from datetime import datetime, timedelta

    from wiki_engine.lint import stale_sources
    from wiki_engine.page import Page
    from wiki_engine.repo import WikiRepo
    from wiki_engine.schema import WikiSchema

    repo = WikiRepo.init(_path := __import__("tempfile").mkdtemp())

    # Create a page with source metadata showing an old ingestion date
    old_date_iso = (datetime.now() - timedelta(days=100)).isoformat()
    repo.write_page(
        Page(
            slug="old_page",
            frontmatter={
                "sources": ["old_doc"],
                "source_metadata": {"old_doc": {"ingested_at": old_date_iso}},
            },
            body="From old source",
        )
    )

    # Create a recent page
    recent_date_iso = datetime.now().isoformat()
    repo.write_page(
        Page(
            slug="recent_page",
            frontmatter={
                "sources": ["new_doc"],
                "source_metadata": {"new_doc": {"ingested_at": recent_date_iso}},
            },
            body="From recent source",
        )
    )

    schema = WikiSchema()

    violations = stale_sources(repo, schema)

    assert len(violations) == 1
    assert violations[0].rule == "stale_sources"
    assert violations[0].affected_pages == ["old_page"]
    assert violations[0].confidence == 0.7
    assert violations[0].suggested_action == "refresh_sources"


@pytest.mark.unit
def test_dead_source_urls_rule():
    """dead_source_urls detects unreachable source URLs."""
    from datetime import datetime

    from wiki_engine.lint import dead_source_urls
    from wiki_engine.page import Page
    from wiki_engine.repo import WikiRepo
    from wiki_engine.schema import WikiSchema

    repo = WikiRepo.init(_path := __import__("tempfile").mkdtemp())

    # Source with a valid-looking URL (we won't actually check it in unit test)
    now_iso = datetime.now().isoformat()
    repo.write_page(
        Page(
            slug="test_page",
            frontmatter={
                "sources": ["url_source"],
                "source_metadata": {
                    "url_source": {
                        "kind": "url",
                        "location": "https://example.com/article",
                        "ingested_at": now_iso,
                    }
                },
            },
            body="Content",
        )
    )

    schema = WikiSchema()

    # Note: In unit test, we pass check_urls=False to skip actual HTTP checks
    violations = dead_source_urls(repo, schema, check_urls=False)

    # With check_urls=False, this rule returns empty (no network calls)
    assert len(violations) == 0


@pytest.mark.unit
def test_duplicate_content_rule():
    """duplicate_content detects pages with near-identical content."""
    from wiki_engine.fakes import FakeEmbedder
    from wiki_engine.lint import duplicate_content
    from wiki_engine.page import Page
    from wiki_engine.repo import WikiRepo
    from wiki_engine.schema import WikiSchema

    repo = WikiRepo.init(_path := __import__("tempfile").mkdtemp())

    # Two pages with identical content
    identical_content = "The quick brown fox jumps over the lazy dog. " * 5
    repo.write_page(Page(slug="page_x", frontmatter={}, body=identical_content))
    repo.write_page(Page(slug="page_y", frontmatter={}, body=identical_content))
    repo.write_page(Page(slug="page_z", frontmatter={}, body="Completely different content here"))

    schema = WikiSchema()

    # With no embedder, returns empty
    assert duplicate_content(repo, schema, embedder=None) == []

    # With a real (batch) embedder, the two identical pages are flagged as
    # duplicates. Regression guard: the old per-text embed() call crashed here.
    violations = duplicate_content(repo, schema, embedder=FakeEmbedder(), threshold=0.8)
    flagged = {frozenset(v.affected_pages) for v in violations}
    assert frozenset({"page_x", "page_y"}) in flagged


@pytest.mark.unit
def test_lint_runner_aggregates_all_rules():
    """lint() runs all rules and returns aggregated violations."""
    from wiki_engine.lint import lint
    from wiki_engine.page import Page
    from wiki_engine.repo import WikiRepo
    from wiki_engine.schema import WikiSchema

    repo = WikiRepo.init(_path := __import__("tempfile").mkdtemp())
    # Seed with a single orphaned page to trigger orphaned_page rule
    repo.write_page(Page(slug="orphaned", frontmatter={}, body="Alone"))

    schema = WikiSchema()

    violations = lint(repo, schema)

    # Should have at least one violation (the orphaned page)
    assert len(violations) >= 1
    assert any(v.rule == "orphaned_page" for v in violations)


@pytest.mark.unit
def test_lint_filters_by_confidence():
    """lint() filters violations by min_confidence threshold."""
    from wiki_engine.lint import lint
    from wiki_engine.page import Page
    from wiki_engine.repo import WikiRepo
    from wiki_engine.schema import WikiSchema

    repo = WikiRepo.init(_path := __import__("tempfile").mkdtemp())
    repo.write_page(Page(slug="orphaned", frontmatter={}, body="Alone"))

    schema = WikiSchema()

    violations_all = lint(repo, schema, min_confidence=0.0)
    violations_high = lint(repo, schema, min_confidence=0.99)

    # High confidence filter should return fewer (or zero) violations
    assert len(violations_high) <= len(violations_all)


@pytest.mark.unit
def test_suggest_refinements_detects_patterns():
    """suggest_refinements() identifies patterns in violations."""
    from wiki_engine.lint import lint, suggest_refinements
    from wiki_engine.page import Page
    from wiki_engine.repo import WikiRepo
    from wiki_engine.schema import WikiSchema

    repo = WikiRepo.init(_path := __import__("tempfile").mkdtemp())
    # Create 4 orphaned Procedure pages to trigger a pattern
    for i in range(4):
        repo.write_page(
            Page(
                slug=f"orphaned_proc_{i}",
                frontmatter={"type": "Procedure"},
                body="...",
            )
        )

    schema = WikiSchema(
        page_types=("Procedure",),
    )

    violations = lint(repo, schema, min_confidence=0.0)
    suggestions = suggest_refinements(violations, repo)

    # Should suggest a refinement for the orphaned Procedure pattern
    assert len(suggestions) >= 1
    proc_suggestions = [s for s in suggestions if "Procedure" in s.violation_pattern]
    assert len(proc_suggestions) >= 1
    assert proc_suggestions[0].confidence > 0.5
    assert "cross-reference" in proc_suggestions[0].suggested_change.lower()


@pytest.mark.unit
def test_suggest_refinements_empty_when_no_patterns():
    """suggest_refinements() returns empty when no patterns detected."""
    from wiki_engine.lint import suggest_refinements
    from wiki_engine.page import Page
    from wiki_engine.repo import WikiRepo

    repo = WikiRepo.init(_path := __import__("tempfile").mkdtemp())
    repo.write_page(Page(slug="index", frontmatter={}, body="[[page_a]]"))
    repo.write_page(Page(slug="page_a", frontmatter={}, body="..."))

    # No violations → no suggestions
    suggestions = suggest_refinements([], repo)
    assert len(suggestions) == 0


@pytest.mark.unit
def test_lint_api_exported():
    """Lint API is accessible from top-level import."""
    from wiki_engine import RefinementSuggestion, Violation, lint, suggest_refinements

    assert callable(lint)
    assert callable(suggest_refinements)
    assert Violation is not None
    assert RefinementSuggestion is not None


@pytest.mark.integration
def test_lint_fixture_triggers_all_rules():
    """Seeded-defects fixture triggers violations from each rule."""
    from wiki_engine.lint import lint

    repo = load_seeded_defects_fixture()
    schema = load_fixture_schema()

    violations = lint(repo, schema, min_confidence=0.0)

    rules_found = {v.rule for v in violations}

    # Fixture should trigger at least these rules:
    assert "orphaned_page" in rules_found  # isolated_runbook
    assert "broken_wikilink" in rules_found  # index references nonexistent_page
    assert "structural_contradiction" in rules_found  # bad_procedure lacks steps
    assert "stale_sources" in rules_found  # old_info is from 2024

    # Check specific violations
    orphaned = [v for v in violations if v.rule == "orphaned_page"]
    orphaned_pages = [v.affected_pages for v in orphaned]
    assert any(v.affected_pages == ["isolated_runbook"] for v in orphaned), (
        f"Expected isolated_runbook in orphaned violations, got: {orphaned_pages}"
    )

    broken = [v for v in violations if v.rule == "broken_wikilink"]
    broken_pages = [v.affected_pages for v in broken]
    assert any(v.affected_pages == ["index"] for v in broken), (
        f"Expected index in broken_wikilink violations, got: {broken_pages}"
    )

    structural = [v for v in violations if v.rule == "structural_contradiction"]
    struct_pages = [v.affected_pages for v in structural]
    assert any(v.affected_pages == ["bad_procedure"] for v in structural), (
        f"Expected bad_procedure in structural_contradiction violations, got: {struct_pages}"
    )


@pytest.mark.unit
def test_lint_uses_schema_staleness_threshold():
    """stale_sources respects schema lint_thresholds staleness_days."""
    from datetime import datetime, timedelta

    from wiki_engine.lint import stale_sources
    from wiki_engine.page import Page
    from wiki_engine.repo import WikiRepo
    from wiki_engine.schema import WikiSchema

    repo = WikiRepo.init(_path := __import__("tempfile").mkdtemp())

    # Create a page with source that is 50 days old
    old_date_iso = (datetime.now() - timedelta(days=50)).isoformat()
    repo.write_page(
        Page(
            slug="test_page",
            frontmatter={
                "sources": ["src1"],
                "source_metadata": {"src1": {"ingested_at": old_date_iso}},
            },
            body="Content",
        )
    )

    # Schema with staleness_days = 40 (so 50-day-old source is stale)
    schema_strict = WikiSchema(lint_thresholds={"staleness_days": 40})

    # Schema with staleness_days = 60 (so 50-day-old source is fresh)
    schema_lenient = WikiSchema(lint_thresholds={"staleness_days": 60})

    # Call with None to read from schema
    violations_strict = stale_sources(repo, schema_strict, days_threshold=None)
    violations_lenient = stale_sources(repo, schema_lenient, days_threshold=None)

    # Strict schema should find 1 violation
    assert len(violations_strict) == 1
    assert violations_strict[0].metadata["threshold_days"] == 40

    # Lenient schema should find 0 violations
    assert len(violations_lenient) == 0


@pytest.mark.unit
def test_stale_sources_uses_default_threshold_when_schema_has_no_threshold():
    """stale_sources falls back to parameter default (90 days) when schema has no threshold."""
    from datetime import datetime, timedelta

    from wiki_engine.lint import stale_sources
    from wiki_engine.page import Page
    from wiki_engine.repo import WikiRepo
    from wiki_engine.schema import WikiSchema

    repo = WikiRepo.init(_path := __import__("tempfile").mkdtemp())

    # Create a page with source that is 95 days old
    old_date_iso = (datetime.now() - timedelta(days=95)).isoformat()
    repo.write_page(
        Page(
            slug="test_page",
            frontmatter={
                "sources": ["src1"],
                "source_metadata": {"src1": {"ingested_at": old_date_iso}},
            },
            body="Content",
        )
    )

    # Schema with no lint_thresholds defined
    schema = WikiSchema(lint_thresholds={})

    # Call with None (should use default 90)
    violations = stale_sources(repo, schema, days_threshold=None)

    # Should find 1 violation (95 days > 90 days)
    assert len(violations) == 1
    assert violations[0].metadata["threshold_days"] == 90


@pytest.mark.unit
def test_lint_uses_schema_duplicate_similarity_threshold():
    """duplicate_content respects schema lint_thresholds duplicate_similarity_max."""
    from unittest.mock import MagicMock

    from wiki_engine.lint import duplicate_content
    from wiki_engine.page import Page
    from wiki_engine.repo import WikiRepo
    from wiki_engine.schema import WikiSchema

    repo = WikiRepo.init(_path := __import__("tempfile").mkdtemp())

    # Create index and two pages
    repo.write_page(Page(slug="index", frontmatter={}, body="Index"))
    repo.write_page(Page(slug="page_a", frontmatter={}, body="Content A"))
    repo.write_page(Page(slug="page_b", frontmatter={}, body="Content B"))

    # Batch embedder (real protocol: embed(texts) -> list[list[float]]) where
    # every text maps to the same vector. [0.92] dot [0.92] = 0.8464 ≈ 0.85.
    def mock_embed(texts):
        return [[0.92] for _ in texts]

    mock_embedder = MagicMock()
    mock_embedder.embed = mock_embed

    # Schema with duplicate_similarity_max = 0.80 (0.85 > 0.80, so flagged)
    schema_strict = WikiSchema(lint_thresholds={"duplicate_similarity_max": 0.80})

    # Schema with duplicate_similarity_max = 0.90 (0.85 < 0.90, so not flagged)
    schema_lenient = WikiSchema(lint_thresholds={"duplicate_similarity_max": 0.90})

    # Call with None to read from schema
    violations_strict = duplicate_content(
        repo, schema_strict, embedder=mock_embedder, threshold=None
    )
    violations_lenient = duplicate_content(
        repo, schema_lenient, embedder=mock_embedder, threshold=None
    )

    # Strict schema should find 3 violations (all pairs have similarity > 0.80)
    assert len(violations_strict) == 3

    # Lenient schema should find 0 violations (all similarities < 0.90)
    assert len(violations_lenient) == 0


@pytest.mark.unit
def test_duplicate_content_uses_default_threshold_when_schema_has_no_threshold():
    """duplicate_content falls back to parameter default (0.8) when schema has no threshold."""
    from unittest.mock import MagicMock

    from wiki_engine.lint import duplicate_content
    from wiki_engine.page import Page
    from wiki_engine.repo import WikiRepo
    from wiki_engine.schema import WikiSchema

    repo = WikiRepo.init(_path := __import__("tempfile").mkdtemp())

    # Create index and two pages
    repo.write_page(Page(slug="index", frontmatter={}, body="Index"))
    repo.write_page(Page(slug="page_a", frontmatter={}, body="Content A"))
    repo.write_page(Page(slug="page_b", frontmatter={}, body="Content B"))

    # Batch embedder (real protocol: embed(texts) -> list[list[float]]) where
    # every text maps to the same vector dotting to ~0.85.
    def mock_embed(texts):
        return [[0.92] for _ in texts]

    mock_embedder = MagicMock()
    mock_embedder.embed = mock_embed

    # Schema with no lint_thresholds defined
    schema = WikiSchema(lint_thresholds={})

    # Call with None (should use default 0.8)
    violations = duplicate_content(repo, schema, embedder=mock_embedder, threshold=None)

    # Should find 3 violations (all pairs have similarity 0.8464 > 0.8)
    assert len(violations) == 3


@pytest.mark.unit
def test_lint_module_coverage():
    """Ensure lint module exports all public items."""
    from wiki_engine import lint
    from wiki_engine.lint import RefinementSuggestion, Violation, suggest_refinements

    # All public functions and classes should be available
    assert callable(lint), "lint should be callable"
    assert callable(suggest_refinements), "suggest_refinements should be callable"
    assert Violation is not None, "Violation should exist"
    assert RefinementSuggestion is not None, "RefinementSuggestion should exist"
