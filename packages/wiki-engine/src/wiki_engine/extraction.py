"""Hybrid NER + LLM fact extraction.

Ported from MemGraphRAG's entity_type_extract.py (NER step) and
schema_fact_extract.py + prompt.py (relation extraction step).
"""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING, Any

from .protocols import Entity, ExtractedFacts, Fact

if TYPE_CHECKING:
    from .llm_backends import _ChatClient

__all__ = ["SpacyNerLlmExtractor"]

# Ported from MemGraphRAG schema_fact_extract.py — entity types to exclude
_EXCLUDED_LABELS = frozenset({"CARDINAL", "ORDINAL", "MONEY", "PERCENT", "QUANTITY"})

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


class SpacyNerLlmExtractor:
    """Hybrid extractor: spaCy NER for entities, LLM for relations.

    Ported from MemGraphRAG entity_type_extract.py + schema_fact_extract.py.
    Degradation: if llm_client is None, returns entities only (no relations).
    """

    def __init__(
        self,
        llm_client: _ChatClient | None = None,
        spacy_model: str = "en_core_web_sm",
        max_entities: int = 50,
    ) -> None:
        self._client = llm_client
        self._max_entities = max_entities
        self._nlp: Any = None
        self._spacy_model = spacy_model

    def _load_spacy(self) -> Any:
        if self._nlp is None:
            import spacy

            self._nlp = spacy.load(self._spacy_model)
        return self._nlp

    def _extract_entities(self, text: str) -> tuple[Entity, ...]:
        """Extract and filter entities using spaCy NER.

        Ported from MemGraphRAG entity_type_extract.py::extract_entities_from_chunk
        + schema_fact_extract.py::filter_entities (excluded labels + dedup).
        """
        nlp = self._load_spacy()
        doc = nlp(text)

        seen: set[tuple[str, str]] = set()
        entities: list[Entity] = []
        for ent in doc.ents:
            if ent.label_ in _EXCLUDED_LABELS:
                continue
            key = (ent.text, ent.label_)
            if key in seen:
                continue
            seen.add(key)
            entities.append(Entity(text=ent.text, entity_type=ent.label_))

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
