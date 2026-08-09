"""Tests for language detection and per-language NER configuration."""

import pytest

from wiki_engine.language import (
    CANONICAL_ENTITY_TYPES,
    DEFAULT_LANGUAGE,
    ENGLISH_STOPWORDS,
    EXCLUDED_ENTITY_TYPES,
    SPACY_MODELS,
    SWEDISH_STOPWORDS,
    canonical_entity_type,
    canonical_fact_type,
    detect_language,
)

SWEDISH = [
    "Hej Anna, jag skickar över avtalet från Volvo på måndag.",
    "Mötet med Ericsson är flyttat till nästa vecka.",
    "Kan du boka ett möte med Peter Svensson i Göteborg?",
    "Vi har skickat offerten till kunden.",
    "Vad kostar licensen?",
    "Fakturan är förfallen och kunden har inte betalat.",
]

ENGLISH = [
    "Hi Anna, I am sending over the contract from Volvo on Monday.",
    "The meeting with Ericsson has been moved to next week.",
    "Please book a meeting with Peter Svensson in Gothenburg.",
    "What does the licence cost?",
    "Invoice 4471 is overdue and needs a reminder.",
    "We have sent the quote to the customer.",
]


@pytest.mark.parametrize("text", SWEDISH)
def test_detects_swedish(text: str) -> None:
    assert detect_language(text) == "sv"


@pytest.mark.parametrize("text", ENGLISH)
def test_detects_english(text: str) -> None:
    assert detect_language(text) == "en"


def test_swedish_without_diacritics_is_detected_from_stopwords() -> None:
    """Plenty of Swedish prose carries no å/ä/ö at all."""
    assert detect_language("Vi har inte kunnat boka in det som du bad om.") == "sv"


@pytest.mark.parametrize("text", ["", "   ", "\n\n", "4471", "%%%"])
def test_no_signal_returns_the_default(text: str) -> None:
    assert detect_language(text) == DEFAULT_LANGUAGE


def test_default_is_configurable() -> None:
    """A seat whose content is mostly Swedish can flip the fallback."""
    assert detect_language("Volvo", default="sv") == "sv"
    assert detect_language("Volvo") == "en"


def test_a_tie_returns_the_default() -> None:
    """One stopword each way is not evidence; do not guess."""
    assert detect_language("the och") == DEFAULT_LANGUAGE


def test_stopword_sets_are_disjoint() -> None:
    """A word in both sets is noise: it cancels out and cannot discriminate."""
    overlap = SWEDISH_STOPWORDS & ENGLISH_STOPWORDS
    assert not overlap, f"stopwords claimed by both languages: {sorted(overlap)}"


def test_every_supported_language_has_a_model() -> None:
    assert SPACY_MODELS == {"en": "en_core_web_md", "sv": "sv_core_news_md"}
    assert DEFAULT_LANGUAGE in SPACY_MODELS


# --- canonical entity types --------------------------------------------------

# The full NER label set of each model, read off nlp.meta["labels"]["ner"].
EN_LABELS = [
    "CARDINAL", "DATE", "EVENT", "FAC", "GPE", "LANGUAGE", "LAW", "LOC", "MONEY",
    "NORP", "ORDINAL", "ORG", "PERCENT", "PERSON", "PRODUCT", "QUANTITY", "TIME",
    "WORK_OF_ART",
]  # fmt: skip
SV_LABELS = ["EVN", "LOC", "MSR", "OBJ", "ORG", "PRS", "TME", "WRK"]


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("PRS", "PERSON"),
        ("ORG", "ORG"),
        ("LOC", "LOC"),
        ("EVN", "EVENT"),
        ("WRK", "WORK"),
        ("OBJ", "PRODUCT"),
        ("TME", "TIME"),
        ("MSR", "QUANTITY"),
    ],
)
def test_swedish_labels_map_to_canonical(label: str, expected: str) -> None:
    assert canonical_entity_type(label, "sv") == expected


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("PERSON", "PERSON"),
        ("ORG", "ORG"),
        ("LOC", "LOC"),
        ("GPE", "LOC"),
        ("FAC", "FACILITY"),
        ("WORK_OF_ART", "WORK"),
        ("EVENT", "EVENT"),
        ("PRODUCT", "PRODUCT"),
        ("DATE", "DATE"),
        ("TIME", "TIME"),
        ("NORP", "NORP"),
        ("LAW", "LAW"),
        ("LANGUAGE", "LANGUAGE"),
        ("CARDINAL", "QUANTITY"),
        ("ORDINAL", "QUANTITY"),
        ("MONEY", "QUANTITY"),
        ("PERCENT", "QUANTITY"),
        ("QUANTITY", "QUANTITY"),
    ],
)
def test_english_labels_map_to_canonical(label: str, expected: str) -> None:
    assert canonical_entity_type(label, "en") == expected


@pytest.mark.parametrize("label", EN_LABELS)
def test_every_english_label_is_mapped(label: str) -> None:
    """An unmapped label would reach the graph as a raw model-specific type."""
    assert canonical_entity_type(label, "en").isupper()


@pytest.mark.parametrize("label", SV_LABELS)
def test_every_swedish_label_is_mapped(label: str) -> None:
    assert canonical_entity_type(label, "sv").isupper()


def test_the_two_models_agree_on_the_shared_concepts() -> None:
    """The point of normalising: one canonical type per real-world concept."""
    for sv, en in [("PRS", "PERSON"), ("ORG", "ORG"), ("LOC", "GPE"), ("EVN", "EVENT")]:
        assert canonical_entity_type(sv, "sv") == canonical_entity_type(en, "en")


def test_unknown_labels_pass_through_unchanged() -> None:
    """A future model revision must not silently drop entities."""
    assert canonical_entity_type("SOMETHING_NEW", "en") == "SOMETHING_NEW"
    assert canonical_entity_type("PERSON", "de") == "PERSON"


def test_numeric_types_are_excluded_in_both_languages() -> None:
    """The bug this fixes: MSR was never filtered, so Swedish amounts leaked in."""
    assert canonical_entity_type("MSR", "sv") in EXCLUDED_ENTITY_TYPES
    for label in ("CARDINAL", "ORDINAL", "MONEY", "PERCENT", "QUANTITY"):
        assert canonical_entity_type(label, "en") in EXCLUDED_ENTITY_TYPES


def test_meaningful_types_are_not_excluded() -> None:
    for label, lang in [("PRS", "sv"), ("PERSON", "en"), ("ORG", "en"), ("DATE", "en")]:
        assert canonical_entity_type(label, lang) not in EXCLUDED_ENTITY_TYPES


# --- fact endpoint types (LLM-supplied, held to a closed vocabulary) ----------


@pytest.mark.parametrize("label", sorted(CANONICAL_ENTITY_TYPES))
def test_canonical_types_are_stable_under_fact_mapping(label: str) -> None:
    """Mapping an already-canonical type must be a no-op, or it is not closed."""
    assert canonical_fact_type(label) == label


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("GPE", "LOC"),
        ("WORK_OF_ART", "WORK"),
        ("FAC", "FACILITY"),
        ("PRS", "PERSON"),
        ("OBJ", "PRODUCT"),
        ("EVN", "EVENT"),
    ],
)
def test_fact_types_are_remapped_regardless_of_document_language(label: str, expected: str) -> None:
    """The LLM's label vocabulary is not bound to the document's language.

    Production seats emit `GPE` on Swedish pages, so a per-language lookup would
    send a perfectly mappable label to MISC.
    """
    assert canonical_fact_type(label) == expected


@pytest.mark.parametrize("label", ["TRANSACTION", "DOCUMENT", "INVOICE", "", "person"])
def test_invented_fact_types_collapse_to_misc(label: str) -> None:
    """Observed on a seat: the model invents types, so the vocabulary grew."""
    assert canonical_fact_type(label) == "MISC"


def test_fact_mapping_keeps_the_vocabulary_closed() -> None:
    """The property the whole change exists for."""
    seen_on_a_seat = [
        "ORG", "PERSON", "DATE", "PRODUCT", "TIME", "LOC",
        "GPE", "NORP", "DOCUMENT", "LANGUAGE", "TRANSACTION", "PERCENT",
    ]  # fmt: skip
    assert {canonical_fact_type(label) for label in seen_on_a_seat} <= CANONICAL_ENTITY_TYPES


def test_quantity_survives_fact_mapping_so_it_can_be_dropped() -> None:
    """It must map to the excluded type, not to MISC, or the drop never fires."""
    for label in ("PERCENT", "MONEY", "MSR", "CARDINAL"):
        assert canonical_fact_type(label) in EXCLUDED_ENTITY_TYPES


def test_known_spacy_labels_are_explicit_not_passed_through() -> None:
    """`not in the map` must mean `invented`, which pass-through would blur."""
    for label in ("NORP", "LAW", "LANGUAGE"):
        assert canonical_entity_type(label, "en") == label
        assert canonical_fact_type(label) == label
