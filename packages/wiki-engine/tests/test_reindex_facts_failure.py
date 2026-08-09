"""`--force` must clear stale records, but not on a failed extraction.

The bug this pins: a failed extraction and an empty one were the same empty
tuple, so `reindex_facts` preserved old records on both while still rewriting
the page. Twelve pages on a production seat survived a full `--force` run with
out-of-vocabulary endpoints intact, and their mtimes said they had been updated.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from wiki_engine.page import Page
from wiki_engine.protocols import Entity, ExtractedFacts, Fact
from wiki_engine.reindex_facts import reindex_facts
from wiki_engine.repo import WikiRepo

STALE_FACT = {
    "head": "Anna",
    "relation": "works_for",
    "tail": "Volvo",
    "head_type": "PERSON",
    "tail_type": "GPE",  # out of vocabulary — what --force was meant to clear
}
STALE_ENTITY = {"text": "Göteborg", "entity_type": "GPE"}


class _Extractor:
    """Returns a canned result; `failed` simulates a timeout."""

    def __init__(
        self,
        entities: tuple[Entity, ...] = (),
        facts: tuple[Fact, ...] = (),
        failed: bool = False,
    ) -> None:
        self._result = ExtractedFacts(entities=entities, facts=facts, relations_failed=failed)
        self.calls = 0

    def extract(self, text: str) -> ExtractedFacts:
        self.calls += 1
        return self._result


@pytest.fixture
def repo(tmp_path: Path) -> WikiRepo:
    repo = WikiRepo(tmp_path / "wiki")
    repo.init(tmp_path / "wiki")
    repo.write_page(
        Page(
            slug="a",
            frontmatter={"title": "a", "facts": [STALE_FACT], "entities": [STALE_ENTITY]},
            body="body",
        )
    )
    return repo


def _page(repo: WikiRepo) -> Page:
    return next(p for p in repo.list_pages() if p.slug == "a")


def test_force_clears_stale_facts_when_extraction_finds_nothing(repo: WikiRepo) -> None:
    """The core fix: empty means empty, so the old records go."""
    result = reindex_facts(repo, _Extractor(), force=True)

    assert "facts" not in _page(repo).frontmatter
    assert "entities" not in _page(repo).frontmatter
    assert result.processed == 1
    assert result.failed == 0


def test_a_failed_extraction_leaves_the_page_untouched(repo: WikiRepo) -> None:
    """A timeout must not delete real facts, and must not move the mtime."""
    path = repo.wiki_dir / "a.md"
    before = path.read_text(encoding="utf-8")
    before_mtime = path.stat().st_mtime_ns

    result = reindex_facts(repo, _Extractor(failed=True), force=True)

    assert path.read_text(encoding="utf-8") == before
    assert path.stat().st_mtime_ns == before_mtime
    assert result.failed == 1
    assert result.processed == 0


def test_a_failed_page_keeps_its_facts(repo: WikiRepo) -> None:
    reindex_facts(repo, _Extractor(failed=True), force=True)

    assert _page(repo).frontmatter["facts"] == [STALE_FACT]


def test_a_failed_page_is_retried_on_the_next_run(repo: WikiRepo) -> None:
    """Untouched means a re-run picks it up — that is the point of not writing."""
    extractor = _Extractor(failed=True)

    reindex_facts(repo, extractor, force=True)
    reindex_facts(repo, extractor, force=True)

    assert extractor.calls == 2


def test_new_records_replace_old_ones(repo: WikiRepo) -> None:
    extractor = _Extractor(
        entities=(Entity("Volvo", "ORG"),),
        facts=(Fact("Anna", "works_for", "Volvo", "PERSON", "ORG"),),
    )

    reindex_facts(repo, extractor, force=True)

    page = _page(repo)
    assert page.frontmatter["facts"][0]["tail_type"] == "ORG"
    assert page.frontmatter["entities"][0]["text"] == "Volvo"


def test_partial_results_still_land(repo: WikiRepo) -> None:
    """Entities found but no relations is a legitimate outcome, not a failure."""
    reindex_facts(repo, _Extractor(entities=(Entity("Volvo", "ORG"),)), force=True)

    page = _page(repo)
    assert page.frontmatter["entities"][0]["text"] == "Volvo"
    assert "facts" not in page.frontmatter


def test_without_force_a_page_with_facts_is_skipped(repo: WikiRepo) -> None:
    """Unchanged behaviour: no --force means only backfill the gaps."""
    extractor = _Extractor()

    result = reindex_facts(repo, extractor, force=False)

    assert extractor.calls == 0
    assert result.processed == 0
    assert _page(repo).frontmatter["facts"] == [STALE_FACT]


def test_the_body_survives_a_clearing_run(repo: WikiRepo) -> None:
    reindex_facts(repo, _Extractor(), force=True)

    assert _page(repo).body.strip() == "body"
