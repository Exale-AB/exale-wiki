"""Language detection and per-language NER configuration.

Seats are bilingual — every `seat.yaml` declares `languages: [sv, en]` — so fact
extraction has to pick the spaCy model that matches the text instead of always
reaching for English.

Detection is a deliberate heuristic rather than a dependency. The decision is
binary (Swedish or English), which is the one case where counting diacritics and
stopwords is genuinely enough; `langdetect` is unmaintained and nondeterministic
without seeding, and `lingua` is a real install on every seat. Keeping this
pure-Python also keeps `import wiki_engine` working with no extras installed.

It is weakest on very short text — a three-word query with no å/ä/ö and no
stopword carries no signal at all — so callers get `default` rather than a guess.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

__all__ = [
    "DEFAULT_LANGUAGE",
    "ENGLISH_STOPWORDS",
    "EXCLUDED_ENTITY_TYPES",
    "SPACY_MODELS",
    "SWEDISH_STOPWORDS",
    "CANONICAL_ENTITY_TYPES",
    "MISC_ENTITY_TYPE",
    "canonical_entity_type",
    "canonical_fact_type",
    "detect_language",
    "language_for_model",
]

DEFAULT_LANGUAGE: Final = "en"

SPACY_MODELS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "en": "en_core_web_md",
        "sv": "sv_core_news_md",
    }
)


def language_for_model(model: str, default: str = DEFAULT_LANGUAGE) -> str:
    """Which language's labels does ``model`` emit?

    Needed because the model that gets loaded is not always the one asked for:
    when a model is missing the extractor falls back, and the labels must then
    be normalised as the fallback's language, not the requested one.
    """
    for language, name in SPACY_MODELS.items():
        if name == model:
            return language
    return default


# --- detection ---------------------------------------------------------------

_SWEDISH_CHARS: Final = frozenset("åäöÅÄÖ")

# å/ä/ö are near-conclusive on their own, so one carries more weight than one
# stopword hit. Capped below so a single diacritic-heavy name cannot outvote a
# whole English paragraph.
_DIACRITIC_WEIGHT: Final = 2

# Deliberately disjoint (asserted by a test): a word claimed by both languages
# cancels out and cannot discriminate, so it is only noise. That rules out the
# tempting overlaps — `under`, `man`, `in`, `so`.
SWEDISH_STOPWORDS: Final[frozenset[str]] = frozenset(
    {
        "och",
        "att",
        "är",
        "för",
        "på",
        "med",
        "som",
        "den",
        "det",
        "en",
        "ett",
        "inte",
        "av",
        "till",
        "har",
        "om",
        "men",
        "kan",
        "ska",
        "vi",
        "du",
        "jag",
        "han",
        "hon",
        "de",
        "från",
        "eller",
        "när",
        "där",
        "här",
        "så",
        "också",
        "efter",
        "över",
        "vid",
        "mot",
        "utan",
        "genom",
        "vara",
        "blir",
        "hos",
        "samt",
        "enligt",
        "något",
        "några",
        "vad",
        "hur",
        "vem",
        "varför",
        "vilken",
        "vilket",
        "vilka",
        "vill",
        "får",
        "gör",
        "finns",
        "ingen",
        "alla",
        "mycket",
        "detta",
        "dessa",
        "sedan",
        "redan",
        "bara",
        "hela",
        "andra",
        "samma",
        "kunde",
        "skulle",
        "blev",
        "varit",
        "denna",
        "dess",
        "sina",
        "sitt",
        "både",
        "än",
        "ju",
        "nu",
        "ännu",
    }
)

ENGLISH_STOPWORDS: Final[frozenset[str]] = frozenset(
    {
        "the",
        "and",
        "is",
        "are",
        "for",
        "with",
        "that",
        "this",
        "of",
        "to",
        "in",
        "on",
        "at",
        "by",
        "from",
        "or",
        "but",
        "can",
        "will",
        "we",
        "you",
        "he",
        "she",
        "they",
        "not",
        "have",
        "has",
        "been",
        "was",
        "were",
        "it",
        "as",
        "be",
        "our",
        "your",
        "their",
        "which",
        "would",
        "about",
        "there",
        "these",
        "those",
        "when",
        "where",
        "what",
        "how",
        "why",
        "who",
        "any",
        "each",
        "more",
        "most",
        "other",
        "some",
        "such",
        "only",
        "own",
        "than",
        "too",
        "very",
        "just",
        "should",
        "could",
        "into",
        "before",
        "between",
        "during",
        "without",
        "through",
        "then",
        "now",
        "here",
        "still",
    }
)

_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)


def detect_language(text: str, default: str = DEFAULT_LANGUAGE) -> str:
    """Return ``"sv"`` or ``"en"`` for ``text``.

    Returns ``default`` when the text carries no signal either way — an empty
    string, a bare number, a single proper noun. Guessing there would send a
    whole document to the wrong NER model on the strength of nothing.
    """
    words = _WORD.findall(text.lower())
    if not words:
        return default

    swedish = sum(word in SWEDISH_STOPWORDS for word in words)
    english = sum(word in ENGLISH_STOPWORDS for word in words)

    diacritics = sum(char in _SWEDISH_CHARS for char in text)
    swedish += _DIACRITIC_WEIGHT * min(diacritics, len(words))

    if swedish == english:
        return default
    return "sv" if swedish > english else "en"


# --- canonical entity types --------------------------------------------------

# The two models speak different vocabularies: en_core_web_md emits 18 labels,
# sv_core_news_md 8. Storing them raw would leave the knowledge graph holding
# PERSON and PRS as unrelated vertex types, so conflict detection and graph
# queries would never connect a Swedish page to an English one about the same
# person. Both are mapped onto one canonical set at extraction time.
#
# GPE -> LOC loses the geopolitical/place distinction. Swedish has no GPE, and
# cross-language consistency is worth more here than the finer English split.
_CANONICAL: Final[Mapping[str, Mapping[str, str]]] = MappingProxyType(
    {
        "en": MappingProxyType(
            {
                "PERSON": "PERSON",
                "ORG": "ORG",
                "GPE": "LOC",
                "LOC": "LOC",
                "FAC": "FACILITY",
                "PRODUCT": "PRODUCT",
                "EVENT": "EVENT",
                "WORK_OF_ART": "WORK",
                "DATE": "DATE",
                "TIME": "TIME",
                # Identity entries rather than pass-through. They are real spaCy
                # labels, and listing them is what lets "not in the map" mean
                # "the LLM invented this" instead of "we never got round to it".
                "NORP": "NORP",
                "LAW": "LAW",
                "LANGUAGE": "LANGUAGE",
                # Numeric and measurement labels are dropped downstream.
                "CARDINAL": "QUANTITY",
                "ORDINAL": "QUANTITY",
                "MONEY": "QUANTITY",
                "PERCENT": "QUANTITY",
                "QUANTITY": "QUANTITY",
            }
        ),
        "sv": MappingProxyType(
            {
                "PRS": "PERSON",
                "ORG": "ORG",
                "LOC": "LOC",
                "OBJ": "PRODUCT",
                "EVN": "EVENT",
                "WRK": "WORK",
                "TME": "TIME",
                "MSR": "QUANTITY",
            }
        ),
    }
)

# Canonical types that carry no knowledge worth storing. Previously this list
# held raw English labels, so on Swedish text it matched nothing and every
# measurement and amount leaked into the graph as an entity.
EXCLUDED_ENTITY_TYPES: Final[frozenset[str]] = frozenset({"QUANTITY"})


MISC_ENTITY_TYPE: Final = "MISC"

# The closed vocabulary. Fact endpoint types are held to it; NER labels are not,
# because those come from a model whose label set we know.
CANONICAL_ENTITY_TYPES: Final[frozenset[str]] = frozenset(
    {value for mapping in _CANONICAL.values() for value in mapping.values()} | {MISC_ENTITY_TYPE}
)

# Every language's labels in one table, for fact endpoints. An LLM's label
# vocabulary is not bound to the document's language — production seats show
# `GPE` on Swedish pages — so looking a fact type up in only the detected
# language's map would send a perfectly mappable label to MISC. Safe to merge:
# the two maps overlap on `ORG` and `LOC` only, and agree on both.
_CANONICAL_ANY_LANGUAGE: Final[Mapping[str, str]] = MappingProxyType(
    {label: value for mapping in _CANONICAL.values() for label, value in mapping.items()}
)


def canonical_entity_type(label: str, language: str) -> str:
    """Map a model-specific NER label onto the shared vocabulary.

    Unknown labels pass through unchanged: these come from spaCy, whose label
    set is known and listed above, so an unknown one means a future model
    revision — which should lose precision, not entities.
    """
    return _CANONICAL.get(language, {}).get(label, label)


def canonical_fact_type(label: str) -> str:
    """Map an LLM-supplied fact endpoint type onto the shared vocabulary.

    Stricter than `canonical_entity_type`, because the source is different. The
    relation prompt asks the model to echo the entity types it was given, and it
    does not always comply — production seats show `GPE` (never echoed: entities
    are normalised to `LOC` before the prompt is built) alongside invented types
    like `TRANSACTION` and `DOCUMENT`. Left alone, the graph's type vocabulary
    grows without bound and cross-language linking fails on the relation edges,
    which is the whole point of normalising.

    Takes no language: see `_CANONICAL_ANY_LANGUAGE`. Anything still outside the
    vocabulary collapses to `MISC` — the relation is worth keeping even when the
    model's idea of its endpoint type is not.
    """
    canonical = _CANONICAL_ANY_LANGUAGE.get(label, label)
    return canonical if canonical in CANONICAL_ENTITY_TYPES else MISC_ENTITY_TYPE
