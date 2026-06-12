from wiki_engine.source import Source, SourceKind


def _src(**kw) -> Source:
    base = {
        "kind": SourceKind.URL,
        "identifier": "https://example.com/a",
        "text": "hello world",
        "title": "Example A",
    }
    base.update(kw)
    return Source(**base)


def test_identity_is_stable_for_same_inputs():
    assert _src().identity() == _src().identity()


def test_identity_changes_when_text_changes():
    assert _src().identity() != _src(text="different").identity()


def test_identity_changes_when_identifier_changes():
    assert _src().identity() != _src(identifier="https://example.com/b").identity()


def test_identity_is_hex_sha256():
    value = _src().identity()
    assert len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def test_categories_default_empty():
    assert _src().categories == ()
