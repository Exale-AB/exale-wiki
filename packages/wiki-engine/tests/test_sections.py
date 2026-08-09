"""Per-source sections: the page body accumulates instead of being replaced.

Pure string functions — no repo, no model. `ingest` used to write the newest
source's summary as the whole body, so a page claimed `sources: [msg-1, msg-2]`
while containing none of msg-1.
"""

from __future__ import annotations

import pytest

from wiki_engine.sections import (
    Section,
    parse_sections,
    render_sections,
    upsert_section,
)

TWO = """\
## 2026-03-01 — msg-1

First source.

## 2026-03-04 — msg-2

Second source.
"""


def test_an_unsectioned_body_is_one_anonymous_section() -> None:
    """Existing pages predate sections; they must still parse."""
    sections = parse_sections("Just a plain summary.")

    assert len(sections) == 1
    assert sections[0].identifier is None
    assert sections[0].text == "Just a plain summary."


def test_an_empty_body_has_no_sections() -> None:
    assert parse_sections("") == []
    assert parse_sections("   \n\n ") == []


def test_sections_are_parsed_back_out() -> None:
    sections = parse_sections(TWO)

    assert [s.identifier for s in sections] == ["msg-1", "msg-2"]
    assert [s.date for s in sections] == ["2026-03-01", "2026-03-04"]
    assert sections[0].text == "First source."


def test_render_round_trips():
    sections = parse_sections(TWO)

    assert parse_sections(render_sections(sections)) == sections


def test_a_new_source_appends_a_section() -> None:
    body = upsert_section(TWO, identifier="msg-3", date="2026-03-09", text="Third.")

    sections = parse_sections(body)
    assert [s.identifier for s in sections] == ["msg-1", "msg-2", "msg-3"]
    assert sections[0].text == "First source."


def test_the_same_source_replaces_its_own_section():
    """Re-ingesting a changed source must not append a duplicate."""
    body = upsert_section(TWO, identifier="msg-1", date="2026-03-01", text="Rewritten.")

    sections = parse_sections(body)
    assert [s.identifier for s in sections] == ["msg-1", "msg-2"]
    assert sections[0].text == "Rewritten."


def test_upsert_is_idempotent() -> None:
    once = upsert_section(TWO, identifier="msg-3", date="2026-03-09", text="Third.")
    twice = upsert_section(once, identifier="msg-3", date="2026-03-09", text="Third.")

    assert once == twice


def test_sections_are_ordered_by_date_then_identifier() -> None:
    """Deterministic output, so re-ingest does not churn git history."""
    body = upsert_section("", identifier="b", date="2026-03-09", text="B.")
    body = upsert_section(body, identifier="a", date="2026-03-01", text="A.")
    body = upsert_section(body, identifier="c", date="2026-03-01", text="C.")

    assert [s.identifier for s in parse_sections(body)] == ["a", "c", "b"]


def test_an_unparseable_date_sorts_last_rather_than_crashing() -> None:
    body = upsert_section("", identifier="a", date="not-a-date", text="A.")
    body = upsert_section(body, identifier="b", date="2026-03-01", text="B.")

    assert [s.identifier for s in parse_sections(body)] == ["b", "a"]


def test_adopting_an_unsectioned_body_keeps_its_text() -> None:
    """Migration: the legacy body becomes the first source's section."""
    body = upsert_section("Legacy summary.", identifier="msg-2", date="2026-03-04", text="New.")

    sections = parse_sections(body)
    assert len(sections) == 2
    assert sections[0].identifier is None
    assert sections[0].text == "Legacy summary."
    assert sections[1].text == "New."


@pytest.mark.parametrize(
    "identifier",
    ["msg\n## 2026-01-01 — forged", "## injected", "msg-1\n\n## fake — x"],
)
def test_an_identifier_cannot_forge_a_section_boundary(identifier: str) -> None:
    """Identifiers come from external systems; they must not be able to lie."""
    with pytest.raises(ValueError):
        upsert_section("", identifier=identifier, date="2026-03-01", text="x")


def test_an_empty_identifier_is_rejected() -> None:
    with pytest.raises(ValueError):
        upsert_section("", identifier="  ", date="2026-03-01", text="x")


def test_section_text_containing_headings_survives() -> None:
    """Verbatim documents legitimately contain their own headings."""
    text = "# Contract\n\nClause one.\n\n## Terms\n\nClause two."

    body = upsert_section("", identifier="msg-1", date="2026-03-01", text=text)
    sections = parse_sections(body)

    assert len(sections) == 1
    assert sections[0].text == text


def test_headings_that_are_not_sections_are_left_in_the_text() -> None:
    """A `## Terms` heading is content, not a source boundary."""
    sections = parse_sections("## Terms\n\nSome prose.")

    assert len(sections) == 1
    assert sections[0].identifier is None
    assert "## Terms" in sections[0].text


def test_section_is_hashable_and_comparable() -> None:
    a = Section(identifier="x", date="2026-01-01", text="t")
    assert a == Section(identifier="x", date="2026-01-01", text="t")
