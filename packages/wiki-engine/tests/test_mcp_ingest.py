"""MCP ingest handler: content-addressed dedup (T01).

Identical text ingested twice must dedupe (same content identity), not pile up
duplicate pages — previously broken because the identifier used id(source_text)
(a memory address), which differs every call.
"""

from pathlib import Path

from wiki_engine.mcp_server import handle_wiki_ingest
from wiki_engine.repo import WikiRepo


def _repo(tmp_path: Path) -> WikiRepo:
    return WikiRepo.init(tmp_path, committer=lambda _r, _m: None)


def _non_reserved_pages(repo: WikiRepo) -> list[str]:
    return [p.slug for p in repo.list_pages()]


def test_ingest_same_text_twice_is_skipped(tmp_path: Path):
    repo = _repo(tmp_path)
    text = "Decision: adopt Slack for team comms by June 30."

    first = handle_wiki_ingest(repo, source_text=text, source_url=None, category="decision")
    second = handle_wiki_ingest(repo, source_text=text, source_url=None, category="decision")

    assert first["status"] == "created"
    assert first["slug"]
    # The second ingest of identical content is deduped, not re-filed.
    assert second["status"] == "skipped"
    assert len(_non_reserved_pages(repo)) == 1


def test_ingest_different_text_creates_distinct_pages(tmp_path: Path):
    repo = _repo(tmp_path)

    handle_wiki_ingest(
        repo, source_text="First note about renewals.", source_url=None, category="note"
    )
    handle_wiki_ingest(
        repo, source_text="Second, unrelated note about hiring.", source_url=None, category="note"
    )

    assert len(_non_reserved_pages(repo)) == 2


def test_ingest_reports_created_status_and_slug(tmp_path: Path):
    repo = _repo(tmp_path)

    result = handle_wiki_ingest(
        repo, source_text="A standalone fact.", source_url=None, category="note"
    )

    assert result["status"] == "created"
    assert result["slug"]
    assert result["title"] == "A standalone fact."
