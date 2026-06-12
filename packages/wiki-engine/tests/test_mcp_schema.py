"""MCP handlers load and enforce the seat schema/AGENTS.md (T02).

Previously the handlers built a default WikiSchema and ignored the seat rulebook,
so off_limits / allowed_source_kinds / lint thresholds were never enforced at
runtime. These tests pin the enforcement to the seat's schema/AGENTS.md.
"""

from pathlib import Path

from wiki_engine.mcp_server import handle_wiki_ingest, handle_wiki_lint
from wiki_engine.repo import WikiRepo

_SCHEMA = """\
---
default_category: General
allowed_source_kinds: [url, file, message]
honesty_rules:
  off_limits_categories: [health-records, legal-disputes]
lint_thresholds:
  duplicate_similarity_max: 0.8
---

# Seat rulebook
"""


def _repo(tmp_path: Path, *, with_schema: bool) -> WikiRepo:
    repo = WikiRepo.init(tmp_path, committer=lambda _r, _m: None)
    if with_schema:
        (repo.schema_dir / "AGENTS.md").write_text(_SCHEMA, encoding="utf-8")
    return repo


def test_ingest_rejects_off_limits_category(tmp_path: Path):
    repo = _repo(tmp_path, with_schema=True)

    result = handle_wiki_ingest(
        repo,
        source_text="A sensitive medical note.",
        source_url=None,
        category="health-records",
    )

    assert result["status"] == "excluded"
    assert result["slug"] == ""
    assert [p.slug for p in repo.list_pages()] == []  # nothing written


def test_ingest_allows_permitted_category(tmp_path: Path):
    repo = _repo(tmp_path, with_schema=True)

    result = handle_wiki_ingest(
        repo,
        source_text="A routine ops note.",
        source_url=None,
        category="ops",
    )

    assert result["status"] == "created"
    assert result["slug"]
    # The per-ingest category is preserved on the page, not flattened to the
    # schema default_category.
    page = repo.read_page(result["slug"])
    assert page is not None
    assert page.frontmatter.get("category") == "ops"


def test_ingest_falls_back_to_default_schema_when_absent(tmp_path: Path):
    repo = _repo(tmp_path, with_schema=False)

    result = handle_wiki_ingest(
        repo,
        source_text="No rulebook present.",
        source_url=None,
        category="note",
    )

    assert result["status"] == "created"


def test_lint_loads_seat_schema(tmp_path: Path):
    repo = _repo(tmp_path, with_schema=True)
    handle_wiki_ingest(repo, source_text="Some page.", source_url=None, category="note")

    out = handle_wiki_lint(repo)

    assert "violations" in out and "suggestions" in out
