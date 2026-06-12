import pytest

from wiki_engine import WikiError
from wiki_engine.page import Page, parse_page, render_page


def test_parse_page_with_frontmatter():
    text = "---\ntitle: Acme AB\ntype: entity\n---\n\nBody about [[Anna Lindqvist]].\n"
    page = parse_page("acme-ab", text)
    assert page.slug == "acme-ab"
    assert page.frontmatter == {"title": "Acme AB", "type": "entity"}
    assert "Body about" in page.body
    assert page.title == "Acme AB"
    assert page.wikilinks == ("Anna Lindqvist",)


def test_parse_page_without_frontmatter_defaults_empty():
    page = parse_page("note", "Just a body, no frontmatter.\n")
    assert page.frontmatter == {}
    assert page.title == "note"  # falls back to slug
    assert page.wikilinks == ()


def test_render_round_trips_frontmatter_and_body():
    page = Page(slug="x", frontmatter={"title": "X", "type": "source"}, body="Hello [[Y]].")
    rendered = render_page(page)
    reparsed = parse_page("x", rendered)
    assert reparsed.frontmatter == {"title": "X", "type": "source"}
    assert reparsed.wikilinks == ("Y",)


def test_render_without_frontmatter_emits_body_only():
    page = Page(slug="x", frontmatter={}, body="Plain body")
    assert render_page(page) == "Plain body\n"


def test_parse_page_rejects_non_mapping_frontmatter():
    with pytest.raises(WikiError, match="must be a mapping"):
        parse_page("x", "---\n- a\n- b\n---\nbody\n")


def test_parse_page_rejects_malformed_frontmatter_yaml():
    with pytest.raises(WikiError, match="invalid page frontmatter"):
        parse_page("x", "---\nfoo: [unclosed\n---\nbody\n")


def test_wikilinks_dedup_is_not_applied_but_whitespace_trimmed():
    page = Page(slug="x", frontmatter={}, body="[[ A ]] and [[B]] and [[A]]")
    assert page.wikilinks == ("A", "B", "A")
