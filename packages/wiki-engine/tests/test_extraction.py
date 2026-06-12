"""Tests for fact extraction data model and extractors."""

import json

import pytest

from wiki_engine.protocols import Entity, ExtractedFacts, Fact, FactExtractor

try:
    import importlib.util

    HAS_SPACY = importlib.util.find_spec("spacy") is not None
except (ImportError, ModuleNotFoundError):
    HAS_SPACY = False


def test_entity_named_tuple():
    e = Entity(text="Acme Corp", entity_type="ORG")
    assert e.text == "Acme Corp"
    assert e.entity_type == "ORG"


def test_fact_named_tuple():
    f = Fact(
        head="Acme Corp",
        relation="acquired",
        tail="WidgetCo",
        head_type="ORG",
        tail_type="ORG",
    )
    assert f.head == "Acme Corp"
    assert f.relation == "acquired"
    assert f.tail == "WidgetCo"


def test_extracted_facts_dataclass():
    entities = (Entity("Acme", "ORG"),)
    facts = (Fact("Acme", "acquired", "Widget", "ORG", "ORG"),)
    ef = ExtractedFacts(entities=entities, facts=facts)
    assert len(ef.entities) == 1
    assert len(ef.facts) == 1


def test_fake_extractor_returns_empty():
    from wiki_engine.fakes import FakeFactExtractor

    extractor = FakeFactExtractor()
    result = extractor.extract("Acme Corp acquired WidgetCo in 2026.")
    assert result.entities == ()
    assert result.facts == ()


def test_fake_extractor_satisfies_protocol():
    from wiki_engine.fakes import FakeFactExtractor

    extractor = FakeFactExtractor()
    assert isinstance(extractor, FactExtractor)


# ---------------------------------------------------------------------------
# SpacyNerLlmExtractor — NER tests
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not HAS_SPACY, reason="spaCy not installed")
def test_spacy_ner_extracts_entities():
    from wiki_engine.extraction import SpacyNerLlmExtractor

    extractor = SpacyNerLlmExtractor(llm_client=None)
    result = extractor.extract("Apple Inc. was founded by Steve Jobs in Cupertino, California.")
    entity_texts = {e.text for e in result.entities}
    assert "Apple Inc." in entity_texts or "Apple" in entity_texts
    assert any("Jobs" in e.text for e in result.entities)
    assert result.facts == ()


@pytest.mark.skipif(not HAS_SPACY, reason="spaCy not installed")
def test_spacy_ner_filters_excluded_labels():
    """CARDINAL, ORDINAL, MONEY, PERCENT, QUANTITY should be excluded."""
    from wiki_engine.extraction import SpacyNerLlmExtractor

    extractor = SpacyNerLlmExtractor(llm_client=None)
    result = extractor.extract("The company earned $5 billion in 2023 with 50,000 employees.")
    entity_types = {e.entity_type for e in result.entities}
    assert "CARDINAL" not in entity_types
    assert "MONEY" not in entity_types
    assert "QUANTITY" not in entity_types


@pytest.mark.skipif(not HAS_SPACY, reason="spaCy not installed")
def test_spacy_ner_deduplicates_entities():
    from wiki_engine.extraction import SpacyNerLlmExtractor

    extractor = SpacyNerLlmExtractor(llm_client=None)
    result = extractor.extract("Apple launched iPhone. Apple also launched iPad.")
    apple_count = sum(1 for e in result.entities if e.text == "Apple")
    assert apple_count <= 1


# ---------------------------------------------------------------------------
# SpacyNerLlmExtractor — relation parsing tests
# ---------------------------------------------------------------------------


class _StubChatClient:
    """Returns a canned JSON response for relation extraction."""

    def __init__(self, response: str):
        self._response = response

    def complete(self, system: str, user: str, *, max_tokens: int) -> str:
        return self._response


@pytest.mark.skipif(not HAS_SPACY, reason="spaCy not installed")
def test_relation_extraction_with_stub_llm():
    from wiki_engine.extraction import SpacyNerLlmExtractor

    canned = json.dumps(
        [
            {
                "head": "Acme Corp",
                "relation": "acquired",
                "tail": "WidgetCo",
                "head_type": "ORG",
                "tail_type": "ORG",
            }
        ]
    )
    extractor = SpacyNerLlmExtractor.__new__(SpacyNerLlmExtractor)
    extractor._client = _StubChatClient(canned)
    extractor._max_entities = 50
    extractor._nlp = None
    extractor._spacy_model = "en_core_web_sm"

    entities = (Entity("Acme Corp", "ORG"), Entity("WidgetCo", "ORG"))
    facts = extractor._extract_relations("Acme Corp acquired WidgetCo.", entities)
    assert len(facts) == 1
    assert facts[0].head == "Acme Corp"
    assert facts[0].relation == "acquired"
    assert facts[0].tail == "WidgetCo"


def test_parse_relations_handles_markdown_fences():
    from wiki_engine.extraction import SpacyNerLlmExtractor

    raw = (
        '```json\n[{"head":"A","relation":"r","tail":"B","head_type":"ORG","tail_type":"ORG"}]\n```'
    )
    facts = SpacyNerLlmExtractor._parse_relations(raw)
    assert len(facts) == 1


def test_parse_relations_handles_empty():
    from wiki_engine.extraction import SpacyNerLlmExtractor

    assert SpacyNerLlmExtractor._parse_relations("[]") == ()
    assert SpacyNerLlmExtractor._parse_relations("not json") == ()
    assert SpacyNerLlmExtractor._parse_relations("{}") == ()


def test_parse_relations_skips_incomplete_items():
    from wiki_engine.extraction import SpacyNerLlmExtractor

    raw = json.dumps(
        [
            {"head": "A", "relation": "r"},  # missing tail/types
            {
                "head": "A",
                "relation": "r",
                "tail": "B",
                "head_type": "ORG",
                "tail_type": "ORG",
            },
        ]
    )
    facts = SpacyNerLlmExtractor._parse_relations(raw)
    assert len(facts) == 1
