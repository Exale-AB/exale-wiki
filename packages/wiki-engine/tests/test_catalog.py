from wiki_engine.catalog import CatalogEntry, parse_index, render_index, upsert_entry


def _entry(slug: str, category: str = "General") -> CatalogEntry:
    return CatalogEntry(title=slug.title(), slug=slug, category=category, summary="sum " + slug)


def test_render_then_parse_round_trips():
    entries = [_entry("acme", "Accounts"), _entry("anna", "People")]
    parsed = parse_index(render_index(entries))
    assert {e.slug for e in parsed} == {"acme", "anna"}
    by_slug = {e.slug: e for e in parsed}
    assert by_slug["acme"].category == "Accounts"
    assert by_slug["acme"].summary == "sum acme"
    assert by_slug["acme"].title == "Acme"


def test_render_groups_by_category_sorted():
    text = render_index([_entry("b", "Zeta"), _entry("a", "Alpha")])
    assert text.index("## Alpha") < text.index("## Zeta")


def test_upsert_adds_new_entry():
    result = upsert_entry([_entry("a")], _entry("b"))
    assert {e.slug for e in result} == {"a", "b"}


def test_upsert_replaces_entry_with_same_slug():
    updated = CatalogEntry(title="Acme", slug="acme", category="Accounts", summary="new")
    result = upsert_entry([_entry("acme", "Accounts")], updated)
    assert len(result) == 1 and result[0].summary == "new"


def test_parse_empty_index_returns_no_entries():
    assert parse_index("# Index\n") == []
