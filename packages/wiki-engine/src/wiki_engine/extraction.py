"""Hybrid NER + LLM fact extraction.

Ported from MemGraphRAG's entity_type_extract.py (NER step) and
schema_fact_extract.py + prompt.py (relation extraction step).
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from .language import (
    DEFAULT_LANGUAGE,
    EXCLUDED_ENTITY_TYPES,
    SPACY_MODELS,
    canonical_entity_type,
    detect_language,
    language_for_model,
)
from .protocols import Entity, ExtractedFacts, Fact

if TYPE_CHECKING:
    from .llm_backends import _ChatClient

__all__ = ["SpacyNerLlmExtractor"]

# Ported verbatim from MemGraphRAG prompt.py
_RELATION_EXTRACTION_SYSTEM = """\
You are an expert in knowledge graph construction and relation extraction.
Your task is to extract relations between given entities from the provided text.

## Instructions:
1. Analyze the text carefully and identify meaningful relations between the provided entities.
2. Only extract relations that are explicitly stated or strongly implied in the text.
3. Use lowercase and underscores for relation names (e.g., "works_for", "located_in").
4. Ensure relations are directional: (subject_entity, relation, object_entity).
5. Do not invent relations that are not supported by the text.

## Output Format:
Return a JSON array of relation triples. Each triple should have:
- "head": the subject entity (exactly as provided)
- "relation": the relation type
- "tail": the object entity (exactly as provided)
- "head_type": the entity type/label of the head entity (exactly as provided)
- "tail_type": the entity type/label of the tail entity (exactly as provided)

If no valid relations can be extracted, return an empty array: []"""

_RELATION_EXTRACTION_USER = """\
## Text:
{text}

## Entities to consider:
{entities}

Please extract all meaningful relations between these entities based on the text above.
Return your answer as a JSON array following the specified format."""


def _warn(message: str) -> None:
    print(f"[wiki_engine.extraction] {message}", file=sys.stderr, flush=True)


def _format_entities_for_prompt(entities: tuple[Entity, ...]) -> str:
    return "\n".join(f"- {e.text} ({e.entity_type})" for e in entities)


def _default_loader(model: str) -> Any:
    import spacy  # lazy: wiki-engine[extraction] is an optional extra

    return spacy.load(model)


class SpacyNerLlmExtractor:
    """Hybrid extractor: spaCy NER for entities, LLM for relations.

    Ported from MemGraphRAG entity_type_extract.py + schema_fact_extract.py, with
    the model chosen per document from the text's language rather than fixed to
    English.

    Degradation: if llm_client is None, returns entities only (no relations); if
    the detected language's model is not installed, falls back to the default
    language's model with one warning.
    """

    def __init__(
        self,
        llm_client: _ChatClient | None = None,
        spacy_model: str | None = None,
        max_entities: int = 50,
        default_language: str = DEFAULT_LANGUAGE,
        model_loader: Callable[[str], Any] | None = None,
    ) -> None:
        self._client = llm_client
        self._max_entities = max_entities
        # Passing spacy_model pins one model and skips detection entirely.
        self._spacy_model = spacy_model
        self._default_language = default_language
        self._load_model = model_loader or _default_loader
        self._nlp_by_model: dict[str, Any] = {}
        self._warned_models: set[str] = set()

    def _model_for(self, text: str) -> str:
        if self._spacy_model is not None:
            return self._spacy_model
        language = detect_language(text, default=self._default_language)
        return SPACY_MODELS.get(language, SPACY_MODELS[self._default_language])

    def _load_spacy(self, model: str) -> tuple[Any, str]:
        """Load and cache ``model``; return it with the model actually used.

        No seat has sv_core_news_sm installed yet, so a missing model has to
        degrade rather than break ingest on every Swedish document. The caller
        needs the model that was *actually* loaded, not the one asked for —
        after a fallback the labels are the fallback's, and normalising them as
        Swedish would corrupt every entity type. A failure to load the fallback
        itself is a real misconfiguration and propagates.
        """
        if model in self._nlp_by_model:
            return self._nlp_by_model[model]

        fallback = SPACY_MODELS[self._default_language]
        try:
            resolved = (self._load_model(model), model)
        except OSError:
            if model == fallback:
                raise
            if model not in self._warned_models:
                self._warned_models.add(model)
                _warn(f"spaCy model {model!r} is not installed; falling back to {fallback!r}")
            resolved = self._load_spacy(fallback)

        self._nlp_by_model[model] = resolved
        return resolved

    def _extract_entities(self, text: str) -> tuple[Entity, ...]:
        """Extract and filter entities using spaCy NER.

        Ported from MemGraphRAG entity_type_extract.py::extract_entities_from_chunk
        + schema_fact_extract.py::filter_entities (excluded labels + dedup), with
        labels normalised to the canonical vocabulary first so the two models'
        output is comparable in the knowledge graph.
        """
        nlp, used_model = self._load_spacy(self._model_for(text))
        language = language_for_model(used_model, default=self._default_language)
        doc = nlp(text)

        seen: set[tuple[str, str]] = set()
        entities: list[Entity] = []
        for ent in doc.ents:
            entity_type = canonical_entity_type(ent.label_, language)
            if entity_type in EXCLUDED_ENTITY_TYPES:
                continue
            key = (ent.text, entity_type)
            if key in seen:
                continue
            seen.add(key)
            entities.append(Entity(text=ent.text, entity_type=entity_type))

        return tuple(entities[: self._max_entities])

    def _extract_relations(self, text: str, entities: tuple[Entity, ...]) -> tuple[Fact, ...]:
        """Extract relations between entities via LLM.

        Ported from MemGraphRAG schema_fact_extract.py::extract_relations_from_chunk.
        """
        if self._client is None or len(entities) < 2:
            return ()

        user_prompt = _RELATION_EXTRACTION_USER.format(
            text=text,
            entities=_format_entities_for_prompt(entities),
        )
        try:
            raw = self._client.complete(_RELATION_EXTRACTION_SYSTEM, user_prompt, max_tokens=800)
            return self._parse_relations(raw)
        except Exception as exc:
            _warn(f"relation extraction failed ({exc}); returning entities only")
            return ()

    @staticmethod
    def _parse_relations(raw: str) -> tuple[Fact, ...]:
        """Parse LLM JSON response into Fact tuples.

        Ported from MemGraphRAG schema_fact_extract.py::_validate_relation.
        """
        text = raw.strip()
        # Strip markdown code fences if present
        if text.startswith("```"):
            lines = text.splitlines()
            lines = [line for line in lines if not line.strip().startswith("```")]
            text = "\n".join(lines)
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return ()

        if not isinstance(data, list):
            return ()

        required = {"head", "relation", "tail", "head_type", "tail_type"}
        facts: list[Fact] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            if not all(item.get(k) for k in required):
                continue
            facts.append(
                Fact(
                    head=item["head"],
                    relation=item["relation"],
                    tail=item["tail"],
                    head_type=item["head_type"],
                    tail_type=item["tail_type"],
                )
            )
        return tuple(facts)

    def extract(self, text: str) -> ExtractedFacts:
        entities = self._extract_entities(text)
        facts = self._extract_relations(text, entities)
        return ExtractedFacts(entities=entities, facts=facts)
