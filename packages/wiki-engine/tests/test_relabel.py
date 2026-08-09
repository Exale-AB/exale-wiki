"""Relabelling persisted facts onto the current canonical vocabulary.

No model, no tokens — a pure function over frontmatter already on disk. This is
what repaired both production seats by hand after #15; the tests pin the
behaviour so it does not have to be done by hand again.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from wiki_engine.language import CANONICAL_ENTITY_TYPES
from wiki_engine.page import Page
from wiki_engine.relabel import relabel_facts
from wiki_engine.repo import WikiRepo


@pytest.fixture
def repo(tmp_path: Path) -> WikiRepo:
    repo = WikiRepo(tmp_path / "wiki")
    repo.init(tmp_path / "wiki")
    return repo


def _fact(head_type: str, tail_type: str) -> dict[str, str]:
    return {
        "head": "Anna",
        "relation": "works_for",
        "tail": "Volvo",
        "head_type": head_type,
        "tail_type": tail_type,
    }


def _write(repo: WikiRepo, slug: str, **frontmatter: object) -> None:
    repo.write_page(Page(slug=slug, frontmatter={"title": slug, **frontmatter}, body="body"))


def _page(repo: WikiRepo, slug: str) -> Page:
    return next(p for p in repo.list_pages() if p.slug == slug)


def test_out_of_vocabulary_fact_endpoints_are_remapped(repo: WikiRepo) -> None:
    """GPE was regenerated on every run and `--force` could not clear it."""
    _write(repo, "a", facts=[_fact("PERSON", "GPE")])

    result = relabel_facts(repo)

    facts = _page(repo, "a").frontmatter["facts"]
    assert facts[0]["tail_type"] == "LOC"
    assert result.facts_relabelled == 1


def test_invented_endpoint_types_collapse_to_misc(repo: WikiRepo) -> None:
    """ACCOUNT, DOCUMENT and TRANSACTION were all found on a seat."""
    _write(repo, "a", facts=[_fact("ACCOUNT", "TRANSACTION")])

    relabel_facts(repo)

    facts = _page(repo, "a").frontmatter["facts"]
    assert (facts[0]["head_type"], facts[0]["tail_type"]) == ("MISC", "MISC")


def test_a_quantity_endpoint_drops_the_fact(repo: WikiRepo) -> None:
    """Same rule extraction applies, so relabelled pages match freshly extracted ones."""
    _write(repo, "a", facts=[_fact("PERSON", "MONEY"), _fact("PERSON", "ORG")])

    result = relabel_facts(repo)

    facts = _page(repo, "a").frontmatter["facts"]
    assert len(facts) == 1
    assert result.facts_dropped == 1


def test_entity_types_are_relabelled_too(repo: WikiRepo) -> None:
    """reindex_facts guards `entities` the same way, so these go stale as well."""
    _write(repo, "a", entities=[{"text": "Göteborg", "entity_type": "GPE"}])

    result = relabel_facts(repo)

    entities = _page(repo, "a").frontmatter["entities"]
    assert entities[0]["entity_type"] == "LOC"
    assert result.entities_relabelled == 1


def test_excluded_entities_are_dropped(repo: WikiRepo) -> None:
    _write(
        repo,
        "a",
        entities=[{"text": "500 kr", "entity_type": "MSR"}, {"text": "Anna", "entity_type": "PRS"}],
    )

    relabel_facts(repo)

    entities = _page(repo, "a").frontmatter["entities"]
    assert [e["text"] for e in entities] == ["Anna"]


def test_pages_already_canonical_are_not_rewritten(repo: WikiRepo) -> None:
    """Idempotent, and no churn in git history on a second run."""
    _write(repo, "a", facts=[_fact("PERSON", "ORG")])
    before = (repo.wiki_dir / "a.md").read_text(encoding="utf-8")

    result = relabel_facts(repo)

    assert result.pages_changed == 0
    assert (repo.wiki_dir / "a.md").read_text(encoding="utf-8") == before


def test_running_twice_changes_nothing_the_second_time(repo: WikiRepo) -> None:
    _write(repo, "a", facts=[_fact("PERSON", "GPE")])

    first = relabel_facts(repo)
    second = relabel_facts(repo)

    assert first.pages_changed == 1
    assert second.pages_changed == 0


def test_pages_without_facts_are_left_alone(repo: WikiRepo) -> None:
    _write(repo, "a")

    result = relabel_facts(repo)

    assert result.pages_changed == 0
    assert "facts" not in _page(repo, "a").frontmatter


def test_the_body_and_other_frontmatter_survive(repo: WikiRepo) -> None:
    """A data migration must not quietly rewrite anything else."""
    _write(repo, "a", category="ops", sources=["x"], facts=[_fact("PERSON", "GPE")])

    relabel_facts(repo)

    page = _page(repo, "a")
    assert page.body.strip() == "body"  # WikiRepo normalises the trailing newline
    assert page.frontmatter["category"] == "ops"
    assert page.frontmatter["sources"] == ["x"]


def test_every_type_ends_up_inside_the_vocabulary(repo: WikiRepo) -> None:
    """The property the pass exists to establish."""
    _write(
        repo,
        "a",
        entities=[{"text": "x", "entity_type": t} for t in ("GPE", "FAC", "DOCUMENT", "PRS")],
        facts=[_fact("WORK_OF_ART", "ACCOUNT"), _fact("EVN", "NORP")],
    )

    relabel_facts(repo)

    page = _page(repo, "a")
    for entity in page.frontmatter["entities"]:
        assert entity["entity_type"] in CANONICAL_ENTITY_TYPES
    for fact in page.frontmatter["facts"]:
        assert fact["head_type"] in CANONICAL_ENTITY_TYPES
        assert fact["tail_type"] in CANONICAL_ENTITY_TYPES


def test_malformed_records_are_skipped_not_crashed(repo: WikiRepo) -> None:
    """Hand-edited frontmatter exists; a migration should not die on it."""
    _write(repo, "a", facts=[{"head": "Anna"}, _fact("PERSON", "GPE")], entities=["not-a-dict"])

    result = relabel_facts(repo)

    assert result.facts_relabelled == 1
    assert len(_page(repo, "a").frontmatter["facts"]) == 2


def test_result_counts_pages_scanned(repo: WikiRepo) -> None:
    _write(repo, "a", facts=[_fact("PERSON", "GPE")])
    _write(repo, "b", facts=[_fact("PERSON", "ORG")])

    result = relabel_facts(repo)

    assert result.pages_scanned == 2
    assert result.pages_changed == 1
