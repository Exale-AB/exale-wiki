"""Unquoted YAML scalars in page frontmatter must not take the server down.

A seat's MCP server never started because ingest left `text: 2026-10-13` (YAML:
a `datetime.date`) and `text: [member]` (YAML: a list) in page frontmatter.
`WikiGraph.rebuild` runs at startup and called `.strip()` on both, so one bad
page crashed the whole process with the host reporting only "connection closed".
"""

from __future__ import annotations

import datetime
from pathlib import Path

import pytest

from wiki_engine.extraction import SpacyNerLlmExtractor
from wiki_engine.knowledge_graph import WikiGraph, facts_from_frontmatter
from wiki_engine.mcp_server import _update_graph_for_page
from wiki_engine.page import parse_page, render_page
from wiki_engine.protocols import Entity, ExtractedFacts, Fact
from wiki_engine.records import coerce_text
from wiki_engine.repo import WikiRepo

UNQUOTED_PAGE = """---
title: Members
type: source
entities:
- text: 2026-10-13
  entity_type: DATE
- text: [member]
  entity_type: ROLE
- text: Acme
  entity_type: ORG
facts:
- head: Acme
  relation: has
  tail: [member]
  head_type: ORG
  tail_type: ROLE
- head: [member]
  relation: joined_on
  tail: 2026-10-13
  head_type: ROLE
  tail_type: DATE
---

Acme has a member who joined 2026-10-13.
"""


@pytest.fixture
def repo(tmp_path: Path) -> WikiRepo:
    repo = WikiRepo(tmp_path / "wiki", committer=lambda *_: None)
    repo.init(tmp_path / "wiki")
    return repo


def _write_raw(repo: WikiRepo, slug: str, text: str) -> None:
    repo.page_path(slug).write_text(text, encoding="utf-8")


def test_unquoted_scalars_parse_to_non_str():
    # Pins the premise: this is what the YAML loader really hands the graph.
    page = parse_page("members", UNQUOTED_PAGE)
    assert page.frontmatter["entities"][0]["text"] == datetime.date(2026, 10, 13)
    assert page.frontmatter["entities"][1]["text"] == ["member"]


def test_rebuild_survives_unquoted_scalars(repo: WikiRepo, capsys: pytest.CaptureFixture[str]):
    _write_raw(repo, "members", UNQUOTED_PAGE)

    graph = WikiGraph()
    graph.rebuild(repo)

    assert graph.stats["passages"] == 1
    assert graph.entity_lookup(["2026-10-13"]) == ["members"]
    assert graph.entity_lookup(["member"]) == ["members"]


def test_rebuild_skips_unusable_record_with_warning_and_keeps_the_rest(
    repo: WikiRepo, capsys: pytest.CaptureFixture[str]
):
    _write_raw(
        repo,
        "mixed",
        "---\ntitle: Mixed\nentities:\n"
        "- text: {a: b}\n  entity_type: ORG\n"
        "- entity_type: ORG\n"
        "- just a string\n"
        "- text: Acme\n  entity_type: ORG\n---\n\nbody\n",
    )

    graph = WikiGraph()
    graph.rebuild(repo)

    assert graph.entity_lookup(["Acme"]) == []  # standalone entity: no fact, no passage edge
    assert graph.stats["entities"] == 1
    err = capsys.readouterr().err
    assert err.count("mixed") == 3  # one warning per skipped record, naming the page


def test_one_bad_page_does_not_stop_the_others(repo: WikiRepo):
    _write_raw(repo, "bad", UNQUOTED_PAGE)
    _write_raw(
        repo,
        "good",
        "---\ntitle: Good\nfacts:\n"
        "- {head: A, relation: r, tail: B, head_type: ORG, tail_type: ORG}\n---\n\nb\n",
    )

    graph = WikiGraph()
    graph.rebuild(repo)

    assert graph.stats["passages"] == 2


def test_update_graph_for_page_survives_unquoted_scalars(repo: WikiRepo):
    _write_raw(repo, "members", UNQUOTED_PAGE)

    graph = WikiGraph()
    _update_graph_for_page(graph, repo, "members")

    assert graph.stats["passages"] == 1


def test_non_list_records_are_ignored_with_warning(capsys: pytest.CaptureFixture[str]):
    extracted = facts_from_frontmatter("p", {"entities": {"text": "x"}, "facts": "oops"})

    assert extracted == ExtractedFacts(entities=(), facts=())
    assert capsys.readouterr().err.count("p") >= 2


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("plain", "plain"),
        (datetime.date(2026, 10, 13), "2026-10-13"),
        (datetime.datetime(2026, 10, 13, 9, 30), "2026-10-13T09:30:00"),
        (2026, "2026"),
        (1.5, "1.5"),
        (["member"], "member"),
        (["a", "b"], "a, b"),
        (True, None),
        (None, None),
        ({"a": 1}, None),
        ([], None),
        ([["nested"]], None),
        ("", None),
        ("   ", None),
    ],
)
def test_coerce_text(value: object, expected: str | None):
    assert coerce_text(value) == expected


@pytest.mark.parametrize("text", ["2026-10-13", "[member]", "yes", "123", "null", "{x}", "a: b"])
def test_entity_text_round_trips_quoted_and_exact(repo: WikiRepo, text: str):
    from wiki_engine.page import Page

    page = Page(
        slug="rt",
        frontmatter={
            "title": "RT",
            "entities": [{"text": text, "entity_type": "X"}],
            "facts": [
                {"head": text, "relation": text, "tail": text, "head_type": "X", "tail_type": "X"}
            ],
        },
        body="b",
    )

    rendered = render_page(page)
    reparsed = parse_page("rt", rendered)

    assert reparsed.frontmatter["entities"][0]["text"] == text
    fact = reparsed.frontmatter["facts"][0]
    assert (fact["head"], fact["relation"], fact["tail"]) == (text, text, text)
    # Quoted on disk, not merely equal after a lucky parse.
    assert f"text: {text}\n" not in rendered
    assert f"tail: {text}\n" not in rendered


def test_written_page_graph_round_trip(repo: WikiRepo):
    from wiki_engine.page import Page

    extracted = ExtractedFacts(
        entities=(Entity("2026-10-13", "DATE"), Entity("[member]", "ROLE")),
        facts=(Fact("[member]", "joined_on", "2026-10-13", "ROLE", "DATE"),),
    )
    repo.write_page(
        Page(
            slug="rt",
            frontmatter={
                "title": "RT",
                "entities": [
                    {"text": e.text, "entity_type": e.entity_type} for e in extracted.entities
                ],
                "facts": [f._asdict() for f in extracted.facts],
            },
            body="b",
        )
    )

    read_back = facts_from_frontmatter("rt", repo.read_page("rt").frontmatter)  # type: ignore[union-attr]

    assert read_back.entities == extracted.entities
    assert read_back.facts == extracted.facts


def test_parse_relations_never_emits_non_str_endpoints():
    raw = (
        '[{"head": ["member"], "relation": "r", "tail": 2026, "head_type": "ORG",'
        ' "tail_type": "DATE"},'
        ' {"head": {"x": 1}, "relation": "r", "tail": "B", "head_type": "A", "tail_type": "B"},'
        ' {"head": true, "relation": "r", "tail": "B", "head_type": "A", "tail_type": "B"}]'
    )

    facts = SpacyNerLlmExtractor._parse_relations(raw)

    assert facts == (Fact("member", "r", "2026", "ORG", "DATE"),)
