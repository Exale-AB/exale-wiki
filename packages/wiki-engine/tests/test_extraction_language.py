"""The extractor picks its spaCy model from the text's language.

These tests inject a fake model loader, so they exercise selection, label
normalisation and degradation without either spaCy model installed.
"""

from __future__ import annotations

from typing import Any

import pytest

from wiki_engine.extraction import SpacyNerLlmExtractor

SWEDISH = "Hej Anna, jag skickar över avtalet från Volvo på måndag."
ENGLISH = "Hi Anna, I am sending over the contract from Volvo on Monday."


class _Ent:
    def __init__(self, text: str, label: str) -> None:
        self.text = text
        self.label_ = label


class _Doc:
    def __init__(self, ents: list[_Ent]) -> None:
        self.ents = ents


class _FakeNlp:
    def __init__(self, ents: list[_Ent]) -> None:
        self._ents = ents

    def __call__(self, text: str) -> _Doc:
        return _Doc(self._ents)


class _Loader:
    """Records which models were asked for; optionally refuses some."""

    def __init__(self, ents: list[_Ent] | None = None, missing: set[str] | None = None) -> None:
        self.requested: list[str] = []
        self._ents = ents or []
        self._missing = missing or set()

    def __call__(self, model: str) -> Any:
        self.requested.append(model)
        if model in self._missing:
            raise OSError(f"[E050] Can't find model '{model}'.")
        return _FakeNlp(self._ents)


def test_swedish_text_loads_the_swedish_model() -> None:
    loader = _Loader()
    SpacyNerLlmExtractor(model_loader=loader).extract(SWEDISH)
    assert loader.requested == ["sv_core_news_sm"]


def test_english_text_loads_the_english_model() -> None:
    loader = _Loader()
    SpacyNerLlmExtractor(model_loader=loader).extract(ENGLISH)
    assert loader.requested == ["en_core_web_sm"]


def test_an_explicit_model_skips_detection() -> None:
    """Existing callers pin a model; that must keep overriding detection."""
    loader = _Loader()
    SpacyNerLlmExtractor(spacy_model="en_core_web_sm", model_loader=loader).extract(SWEDISH)
    assert loader.requested == ["en_core_web_sm"]


def test_default_language_applies_when_the_text_has_no_signal() -> None:
    loader = _Loader()
    SpacyNerLlmExtractor(default_language="sv", model_loader=loader).extract("4471")
    assert loader.requested == ["sv_core_news_sm"]


def test_each_model_is_loaded_once_and_cached() -> None:
    loader = _Loader()
    extractor = SpacyNerLlmExtractor(model_loader=loader)
    extractor.extract(SWEDISH)
    extractor.extract(SWEDISH)
    extractor.extract(ENGLISH)
    assert loader.requested == ["sv_core_news_sm", "en_core_web_sm"]


def test_a_missing_model_falls_back_to_the_default(capsys: pytest.CaptureFixture[str]) -> None:
    """No seat has sv_core_news_sm yet — this must degrade, not raise."""
    loader = _Loader(missing={"sv_core_news_sm"})
    extractor = SpacyNerLlmExtractor(model_loader=loader)

    result = extractor.extract(SWEDISH)

    assert loader.requested == ["sv_core_news_sm", "en_core_web_sm"]
    assert result.entities == ()
    assert "sv_core_news_sm" in capsys.readouterr().err


def test_the_missing_model_warning_is_not_repeated(capsys: pytest.CaptureFixture[str]) -> None:
    """One warning per process, not one per ingested document."""
    extractor = SpacyNerLlmExtractor(model_loader=_Loader(missing={"sv_core_news_sm"}))
    extractor.extract(SWEDISH)
    capsys.readouterr()

    extractor.extract(SWEDISH)

    assert capsys.readouterr().err == ""


def test_a_missing_default_model_propagates() -> None:
    """Falling back to a model that is also absent is a real failure."""
    extractor = SpacyNerLlmExtractor(
        model_loader=_Loader(missing={"sv_core_news_sm", "en_core_web_sm"})
    )
    with pytest.raises(OSError):
        extractor.extract(SWEDISH)


def test_swedish_labels_are_normalised() -> None:
    loader = _Loader([_Ent("Anna", "PRS"), _Ent("Volvo", "ORG"), _Ent("Göteborg", "LOC")])
    result = SpacyNerLlmExtractor(model_loader=loader).extract(SWEDISH)
    assert [(e.text, e.entity_type) for e in result.entities] == [
        ("Anna", "PERSON"),
        ("Volvo", "ORG"),
        ("Göteborg", "LOC"),
    ]


def test_english_gpe_is_normalised_to_the_shared_type() -> None:
    loader = _Loader([_Ent("Gothenburg", "GPE")])
    result = SpacyNerLlmExtractor(model_loader=loader).extract(ENGLISH)
    assert result.entities[0].entity_type == "LOC"


def test_swedish_measurements_are_excluded() -> None:
    """MSR was never in the English exclusion list, so amounts leaked in."""
    loader = _Loader([_Ent("Anna", "PRS"), _Ent("500 kr", "MSR")])
    result = SpacyNerLlmExtractor(model_loader=loader).extract(SWEDISH)
    assert [e.text for e in result.entities] == ["Anna"]


def test_english_numerics_are_still_excluded() -> None:
    loader = _Loader([_Ent("Anna", "PERSON"), _Ent("$500", "MONEY"), _Ent("three", "CARDINAL")])
    result = SpacyNerLlmExtractor(model_loader=loader).extract(ENGLISH)
    assert [e.text for e in result.entities] == ["Anna"]


def test_duplicate_entities_are_deduplicated_after_normalisation() -> None:
    """GPE and LOC both become LOC; the same place must not appear twice."""
    loader = _Loader([_Ent("Sverige", "LOC"), _Ent("Sverige", "LOC")])
    result = SpacyNerLlmExtractor(model_loader=loader).extract(SWEDISH)
    assert len(result.entities) == 1


def test_max_entities_still_caps_the_result() -> None:
    loader = _Loader([_Ent(f"Person {i}", "PRS") for i in range(10)])
    result = SpacyNerLlmExtractor(model_loader=loader, max_entities=3).extract(SWEDISH)
    assert len(result.entities) == 3


# --- against the real models -------------------------------------------------

_HAS_SV = _HAS_EN = False
try:  # pragma: no cover - depends on which models the machine has
    import spacy

    spacy.load("sv_core_news_sm")
    _HAS_SV = True
except Exception:  # noqa: BLE001 - spacy or the model is absent
    pass
try:  # pragma: no cover
    import spacy

    spacy.load("en_core_web_sm")
    _HAS_EN = True
except Exception:  # noqa: BLE001
    pass


@pytest.mark.skipif(not (_HAS_SV and _HAS_EN), reason="both spaCy models required")
def test_real_models_produce_the_same_canonical_type_for_the_same_person() -> None:
    """The whole point: a Swedish page and an English one agree in the graph."""
    extractor = SpacyNerLlmExtractor()

    sv = extractor.extract("Peter Svensson arbetar på Volvo i Göteborg sedan förra året.")
    en = extractor.extract("Peter Svensson has worked at Volvo in Gothenburg since last year.")

    def types_for(result: Any, name: str) -> set[str]:
        return {e.entity_type for e in result.entities if name in e.text}

    assert types_for(sv, "Peter") == types_for(en, "Peter") == {"PERSON"}
