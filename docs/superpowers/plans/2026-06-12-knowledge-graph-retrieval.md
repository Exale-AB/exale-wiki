# Knowledge Graph Retrieval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a three-layer knowledge graph (entity/fact/schema/passage) with hybrid NER+LLM extraction, igraph PPR retrieval, and conflict auto-resolution to the wiki-engine.

**Architecture:** Facts are extracted during ingest via spaCy NER + Hermes LLM, stored in page frontmatter (markdown stays system of record), and indexed into an igraph-backed knowledge graph persisted as GraphML. Retrieval fuses three signals (structural, graph-PPR, vector) via Reciprocal Rank Fusion. Conflict detection groups facts by shared entities; resolution calls the LLM.

**Tech Stack:** Python 3.11, igraph (graph + PPR), spaCy en_core_web_sm (NER), OpenAI SDK via Hermes proxy (relation extraction + conflict resolution), pytest, existing wiki-engine DI seam pattern.

**Spec:** `docs/superpowers/specs/2026-06-12-knowledge-graph-retrieval-design.md`

**MemGraphRAG repo:** `github.com/XMUDeepLIT/MemGraphRAG` — port code directly where noted.

---

## File Map

### New files

| File | Responsibility |
|------|---------------|
| `packages/wiki-engine/src/wiki_engine/extraction.py` | `SpacyNerLlmExtractor` — hybrid NER + LLM relation extraction. Ports from MemGraphRAG `entity_type_extract.py` + `schema_fact_extract.py` + `prompt.py`. |
| `packages/wiki-engine/src/wiki_engine/knowledge_graph.py` | `WikiGraph` — igraph-backed three-layer graph with PPR. Ports from MemGraphRAG `memory.py` dedup + `Memgraphrag` graph build. |
| `packages/wiki-engine/src/wiki_engine/conflicts.py` | `HermesConflictResolver`, `fact_contradiction` lint rule. Ports from MemGraphRAG `resolve_conflict.py` + `prompt.py` conflict prompts. |
| `packages/wiki-engine/src/wiki_engine/reindex_facts.py` | Backfill CLI: extract facts for all pages, rebuild graph. |
| `tests/test_extraction.py` | Tests for `SpacyNerLlmExtractor` + `FakeFactExtractor`. |
| `tests/test_knowledge_graph.py` | Tests for `WikiGraph` (build, update, PPR, rebuild, save/load). |
| `tests/test_conflicts.py` | Tests for conflict detection + resolution. |
| `tests/test_reindex_facts.py` | Tests for backfill CLI. |
| `tests/test_retriever_graph.py` | Tests for graph-enhanced retrieval + RRF fusion. |

### Modified files

| File | Changes |
|------|---------|
| `protocols.py` | Add `Entity`, `Fact`, `ExtractedFacts`, `FactExtractor` protocol. |
| `fakes.py` | Add `FakeFactExtractor`, `FakeConflictResolver`. |
| `ingest.py` | Add optional `extractor`/`graph` params, extract facts, update graph in txn. |
| `retrieval.py` | Add `graph`/`extractor` to `Retriever`, `_graph_retrieve`, `_fuse` (RRF). |
| `lint.py` | Wire `fact_contradiction` into default rules. |
| `mcp_server.py` | Extend `ToolContext`, add `wiki_resolve_conflicts` + `wiki_graph_stats` tools, wire graph into retriever construction. |
| `__main__.py` | Wire extraction/graph/resolver at startup. |
| `__init__.py` | Export new public names. |
| `pyproject.toml` (wiki-engine) | Add `igraph>=0.11` to deps, `extraction` optional extra for spaCy. |
| `pyproject.toml` (workspace root) | Add `wiki-engine[extraction]` to dev deps. |

---

## Task 1: Data Model — Protocols and Fakes

**Files:**
- Modify: `packages/wiki-engine/src/wiki_engine/protocols.py`
- Modify: `packages/wiki-engine/src/wiki_engine/fakes.py`
- Create: `packages/wiki-engine/tests/test_extraction.py` (first test only)

- [ ] **Step 1: Write failing test for Entity/Fact/ExtractedFacts data model**

```python
# packages/wiki-engine/tests/test_extraction.py
"""Tests for fact extraction data model and extractors."""
from wiki_engine.protocols import Entity, ExtractedFacts, Fact


def test_entity_named_tuple():
    e = Entity(text="Acme Corp", entity_type="ORG")
    assert e.text == "Acme Corp"
    assert e.entity_type == "ORG"


def test_fact_named_tuple():
    f = Fact(head="Acme Corp", relation="acquired", tail="WidgetCo",
             head_type="ORG", tail_type="ORG")
    assert f.head == "Acme Corp"
    assert f.relation == "acquired"
    assert f.tail == "WidgetCo"


def test_extracted_facts_dataclass():
    entities = (Entity("Acme", "ORG"),)
    facts = (Fact("Acme", "acquired", "Widget", "ORG", "ORG"),)
    ef = ExtractedFacts(entities=entities, facts=facts)
    assert len(ef.entities) == 1
    assert len(ef.facts) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/nandanthakur/projects/exale && uv run pytest packages/wiki-engine/tests/test_extraction.py -v`
Expected: `ImportError: cannot import name 'Entity' from 'wiki_engine.protocols'`

- [ ] **Step 3: Add data types to protocols.py**

Add after the existing `Vector` type alias in `packages/wiki-engine/src/wiki_engine/protocols.py`:

```python
from typing import NamedTuple, Protocol
from dataclasses import dataclass

class Entity(NamedTuple):
    text: str
    entity_type: str

class Fact(NamedTuple):
    head: str
    relation: str
    tail: str
    head_type: str
    tail_type: str

@dataclass(frozen=True)
class ExtractedFacts:
    entities: tuple[Entity, ...]
    facts: tuple[Fact, ...]

class FactExtractor(Protocol):
    def extract(self, text: str) -> ExtractedFacts: ...
```

Update `__all__` to include: `"Entity", "ExtractedFacts", "Fact", "FactExtractor"`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/nandanthakur/projects/exale && uv run pytest packages/wiki-engine/tests/test_extraction.py -v`
Expected: 3 passed

- [ ] **Step 5: Write failing test for FakeFactExtractor**

Append to `packages/wiki-engine/tests/test_extraction.py`:

```python
from wiki_engine.fakes import FakeFactExtractor


def test_fake_extractor_returns_empty():
    extractor = FakeFactExtractor()
    result = extractor.extract("Acme Corp acquired WidgetCo in 2026.")
    assert result.entities == ()
    assert result.facts == ()


def test_fake_extractor_satisfies_protocol():
    from wiki_engine.protocols import FactExtractor
    extractor = FakeFactExtractor()
    assert isinstance(extractor, FactExtractor)
```

- [ ] **Step 6: Run test to verify it fails**

Run: `cd /Users/nandanthakur/projects/exale && uv run pytest packages/wiki-engine/tests/test_extraction.py::test_fake_extractor_returns_empty -v`
Expected: `ImportError: cannot import name 'FakeFactExtractor'`

- [ ] **Step 7: Add FakeFactExtractor to fakes.py**

Add to `packages/wiki-engine/src/wiki_engine/fakes.py`:

```python
from .protocols import ExtractedFacts

class FakeFactExtractor:
    """No-op extractor: returns empty entities and facts (no spaCy/LLM needed)."""

    def extract(self, text: str) -> ExtractedFacts:
        return ExtractedFacts(entities=(), facts=())
```

Update `__all__` to include `"FakeFactExtractor"`.

- [ ] **Step 8: Run all extraction tests to verify they pass**

Run: `cd /Users/nandanthakur/projects/exale && uv run pytest packages/wiki-engine/tests/test_extraction.py -v`
Expected: 5 passed

- [ ] **Step 9: Run full suite to check nothing broke**

Run: `cd /Users/nandanthakur/projects/exale && uv run pytest`
Expected: All pass, coverage >= 80%

- [ ] **Step 10: Commit**

```bash
git add packages/wiki-engine/src/wiki_engine/protocols.py packages/wiki-engine/src/wiki_engine/fakes.py packages/wiki-engine/tests/test_extraction.py
git commit -m "feat: Entity/Fact/ExtractedFacts data model + FakeFactExtractor"
```

---

## Task 2: Dependencies — igraph + spaCy optional extra

**Files:**
- Modify: `packages/wiki-engine/pyproject.toml`
- Modify: `pyproject.toml` (workspace root)

- [ ] **Step 1: Add igraph to wiki-engine dependencies, spaCy as optional extra**

In `packages/wiki-engine/pyproject.toml`, change:

```toml
dependencies = ["pyyaml>=6.0", "psycopg[binary]>=3.1"]
```

to:

```toml
dependencies = ["pyyaml>=6.0", "psycopg[binary]>=3.1", "igraph>=0.11"]
```

And add extraction extra under `[project.optional-dependencies]`:

```toml
extraction = ["spacy>=3.7"]
```

- [ ] **Step 2: Add wiki-engine[extraction] to workspace dev deps**

In root `pyproject.toml`, change:

```toml
"wiki-engine[llm]",
```

to:

```toml
"wiki-engine[llm,extraction]",
```

- [ ] **Step 3: Sync and verify**

Run: `cd /Users/nandanthakur/projects/exale && uv sync`
Expected: igraph installed. spaCy installed in dev venv. No errors.

- [ ] **Step 4: Verify igraph is importable**

Run: `cd /Users/nandanthakur/projects/exale && uv run python -c "import igraph; print(igraph.__version__)"`
Expected: Version printed (e.g., `0.11.8`)

- [ ] **Step 5: Download spaCy model**

Run: `cd /Users/nandanthakur/projects/exale && uv run python -m spacy download en_core_web_sm`
Expected: Model downloaded successfully.

- [ ] **Step 6: Run full suite to verify deps don't break anything**

Run: `cd /Users/nandanthakur/projects/exale && uv run pytest`
Expected: All pass, coverage >= 80%

- [ ] **Step 7: Commit**

```bash
git add packages/wiki-engine/pyproject.toml pyproject.toml uv.lock
git commit -m "chore: add igraph dep + spaCy extraction optional extra"
```

---

## Task 3: Hybrid Extraction — SpacyNerLlmExtractor

**Files:**
- Create: `packages/wiki-engine/src/wiki_engine/extraction.py`
- Modify: `packages/wiki-engine/tests/test_extraction.py`

This module ports from MemGraphRAG's `entity_type_extract.py` (NER), `schema_fact_extract.py` (relation extraction), and `prompt.py` (prompts).

- [ ] **Step 1: Write failing test for spaCy NER extraction**

Append to `packages/wiki-engine/tests/test_extraction.py`:

```python
import pytest

try:
    import spacy
    HAS_SPACY = True
except ImportError:
    HAS_SPACY = False


@pytest.mark.skipif(not HAS_SPACY, reason="spaCy not installed")
def test_spacy_ner_extracts_entities():
    from wiki_engine.extraction import SpacyNerLlmExtractor
    from wiki_engine.fakes import FakeFactExtractor

    # Use a stub LLM client that returns empty relations — we're testing NER only
    extractor = SpacyNerLlmExtractor(llm_client=None)
    result = extractor.extract("Apple Inc. was founded by Steve Jobs in Cupertino, California.")
    entity_texts = {e.text for e in result.entities}
    # spaCy en_core_web_sm should find at least Apple Inc. and Steve Jobs
    assert "Apple Inc." in entity_texts or "Apple" in entity_texts
    assert any("Jobs" in e.text for e in result.entities)
    # No relations without an LLM client
    assert result.facts == ()


@pytest.mark.skipif(not HAS_SPACY, reason="spaCy not installed")
def test_spacy_ner_filters_excluded_labels():
    """CARDINAL, ORDINAL, MONEY, PERCENT, QUANTITY should be excluded (MemGraphRAG filter)."""
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
    # Repeat entity to test dedup
    result = extractor.extract("Apple launched iPhone. Apple also launched iPad.")
    apple_count = sum(1 for e in result.entities if e.text == "Apple")
    assert apple_count <= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/nandanthakur/projects/exale && uv run pytest packages/wiki-engine/tests/test_extraction.py::test_spacy_ner_extracts_entities -v`
Expected: `ImportError: cannot import name 'SpacyNerLlmExtractor'`

- [ ] **Step 3: Create extraction.py with NER step**

Create `packages/wiki-engine/src/wiki_engine/extraction.py`:

```python
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
_RELATION_EXTRACTION_SYSTEM = """You are an expert in knowledge graph construction and relation extraction.
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

_RELATION_EXTRACTION_USER = """## Text:
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
            raw = self._client.complete(
                _RELATION_EXTRACTION_SYSTEM, user_prompt, max_tokens=800
            )
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
            lines = [l for l in lines if not l.strip().startswith("```")]
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
```

- [ ] **Step 4: Run NER tests to verify they pass**

Run: `cd /Users/nandanthakur/projects/exale && uv run pytest packages/wiki-engine/tests/test_extraction.py -v`
Expected: All pass (spaCy tests pass, earlier tests still pass)

- [ ] **Step 5: Write test for LLM relation extraction with a stub client**

Append to `packages/wiki-engine/tests/test_extraction.py`:

```python
class StubChatClient:
    """Returns a canned JSON response for relation extraction."""

    def __init__(self, response: str):
        self._response = response

    def complete(self, system: str, user: str, *, max_tokens: int) -> str:
        return self._response


def test_relation_extraction_with_stub_llm():
    from wiki_engine.extraction import SpacyNerLlmExtractor

    canned = json.dumps([
        {
            "head": "Acme Corp",
            "relation": "acquired",
            "tail": "WidgetCo",
            "head_type": "ORG",
            "tail_type": "ORG",
        }
    ])
    extractor = SpacyNerLlmExtractor.__new__(SpacyNerLlmExtractor)
    extractor._client = StubChatClient(canned)
    extractor._max_entities = 50
    extractor._nlp = None
    extractor._spacy_model = "en_core_web_sm"

    from wiki_engine.protocols import Entity
    entities = (Entity("Acme Corp", "ORG"), Entity("WidgetCo", "ORG"))
    facts = extractor._extract_relations("Acme Corp acquired WidgetCo.", entities)
    assert len(facts) == 1
    assert facts[0].head == "Acme Corp"
    assert facts[0].relation == "acquired"
    assert facts[0].tail == "WidgetCo"


def test_parse_relations_handles_markdown_fences():
    from wiki_engine.extraction import SpacyNerLlmExtractor

    raw = '```json\n[{"head":"A","relation":"r","tail":"B","head_type":"ORG","tail_type":"ORG"}]\n```'
    facts = SpacyNerLlmExtractor._parse_relations(raw)
    assert len(facts) == 1


def test_parse_relations_handles_empty():
    from wiki_engine.extraction import SpacyNerLlmExtractor

    assert SpacyNerLlmExtractor._parse_relations("[]") == ()
    assert SpacyNerLlmExtractor._parse_relations("not json") == ()
    assert SpacyNerLlmExtractor._parse_relations("{}") == ()


def test_parse_relations_skips_incomplete_items():
    from wiki_engine.extraction import SpacyNerLlmExtractor

    raw = json.dumps([
        {"head": "A", "relation": "r"},  # missing tail/types
        {"head": "A", "relation": "r", "tail": "B", "head_type": "ORG", "tail_type": "ORG"},
    ])
    facts = SpacyNerLlmExtractor._parse_relations(raw)
    assert len(facts) == 1
```

Add `import json` at the top of the test file if not already present.

- [ ] **Step 6: Run to verify they pass**

Run: `cd /Users/nandanthakur/projects/exale && uv run pytest packages/wiki-engine/tests/test_extraction.py -v`
Expected: All pass

- [ ] **Step 7: Run full suite + lint**

Run: `cd /Users/nandanthakur/projects/exale && uv run pytest && uv run ruff check .`
Expected: All pass, no lint errors

- [ ] **Step 8: Commit**

```bash
git add packages/wiki-engine/src/wiki_engine/extraction.py packages/wiki-engine/tests/test_extraction.py
git commit -m "feat: SpacyNerLlmExtractor — hybrid NER + LLM fact extraction"
```

---

## Task 4: Knowledge Graph — WikiGraph

**Files:**
- Create: `packages/wiki-engine/src/wiki_engine/knowledge_graph.py`
- Create: `packages/wiki-engine/tests/test_knowledge_graph.py`

Ports from MemGraphRAG `memory.py` (three-layer dedup logic) and `Memgraphrag` (igraph construction).

- [ ] **Step 1: Write failing tests for WikiGraph core operations**

Create `packages/wiki-engine/tests/test_knowledge_graph.py`:

```python
"""Tests for the WikiGraph three-layer knowledge graph."""
import pytest
from wiki_engine.protocols import Entity, ExtractedFacts, Fact
from wiki_engine.knowledge_graph import WikiGraph


def _sample_facts() -> ExtractedFacts:
    return ExtractedFacts(
        entities=(
            Entity("Acme Corp", "ORG"),
            Entity("WidgetCo", "ORG"),
            Entity("Jane Smith", "PERSON"),
        ),
        facts=(
            Fact("Acme Corp", "acquired", "WidgetCo", "ORG", "ORG"),
            Fact("Jane Smith", "announced", "Acme Corp", "PERSON", "ORG"),
        ),
    )


def test_empty_graph():
    g = WikiGraph()
    assert g.stats["entities"] == 0
    assert g.stats["facts"] == 0
    assert g.stats["schemas"] == 0
    assert g.stats["passages"] == 0


def test_update_adds_vertices_and_edges():
    g = WikiGraph()
    g.update("acme-acquires-widgetco", _sample_facts())
    assert g.stats["entities"] == 3  # Acme, WidgetCo, Jane
    assert g.stats["facts"] == 2
    assert g.stats["schemas"] == 2  # ORG|acquired|ORG, PERSON|announced|ORG
    assert g.stats["passages"] == 1


def test_update_is_idempotent():
    g = WikiGraph()
    g.update("page-a", _sample_facts())
    g.update("page-a", _sample_facts())
    assert g.stats["passages"] == 1
    assert g.stats["facts"] == 2


def test_update_second_page_shares_entities():
    g = WikiGraph()
    g.update("page-a", _sample_facts())
    g.update("page-b", ExtractedFacts(
        entities=(Entity("Acme Corp", "ORG"), Entity("Bob", "PERSON")),
        facts=(Fact("Bob", "works_at", "Acme Corp", "PERSON", "ORG"),),
    ))
    assert g.stats["passages"] == 2
    # "Acme Corp" entity is shared, not duplicated
    assert g.stats["entities"] == 4  # Acme, WidgetCo, Jane, Bob


def test_entity_lookup():
    g = WikiGraph()
    g.update("page-a", _sample_facts())
    g.update("page-b", ExtractedFacts(
        entities=(Entity("Acme Corp", "ORG"), Entity("Bob", "PERSON")),
        facts=(Fact("Bob", "works_at", "Acme Corp", "PERSON", "ORG"),),
    ))
    slugs = g.entity_lookup(["Acme Corp"])
    assert "page-a" in slugs
    assert "page-b" in slugs


def test_entity_lookup_normalizes_case():
    g = WikiGraph()
    g.update("page-a", _sample_facts())
    slugs = g.entity_lookup(["acme corp"])
    assert "page-a" in slugs


def test_entity_lookup_no_match():
    g = WikiGraph()
    g.update("page-a", _sample_facts())
    assert g.entity_lookup(["Nonexistent"]) == []


def test_ppr_returns_ranked_passages():
    g = WikiGraph()
    g.update("page-a", _sample_facts())
    g.update("page-b", ExtractedFacts(
        entities=(Entity("Acme Corp", "ORG"), Entity("Bob", "PERSON")),
        facts=(Fact("Bob", "works_at", "Acme Corp", "PERSON", "ORG"),),
    ))
    ranked = g.ppr(["page-a"], top_k=5)
    slugs = [slug for slug, _score in ranked]
    assert "page-a" in slugs
    # page-b should also appear (connected via shared Acme Corp entity)
    assert "page-b" in slugs


def test_ppr_empty_seeds():
    g = WikiGraph()
    g.update("page-a", _sample_facts())
    assert g.ppr([], top_k=5) == []


def test_remove_page():
    g = WikiGraph()
    g.update("page-a", _sample_facts())
    assert g.stats["passages"] == 1
    g.remove_page("page-a")
    assert g.stats["passages"] == 0


def test_remove_page_nonexistent():
    g = WikiGraph()
    g.remove_page("nope")  # should not raise
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/nandanthakur/projects/exale && uv run pytest packages/wiki-engine/tests/test_knowledge_graph.py -v`
Expected: `ModuleNotFoundError: No module named 'wiki_engine.knowledge_graph'`

- [ ] **Step 3: Implement WikiGraph**

Create `packages/wiki-engine/src/wiki_engine/knowledge_graph.py`:

```python
"""Three-layer knowledge graph backed by igraph + GraphML.

Ported from MemGraphRAG memory.py (dedup logic, three-layer structure) and
Memgraphrag (igraph construction, PPR retrieval).
"""
from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import igraph as ig

from .protocols import Entity, ExtractedFacts, Fact

__all__ = ["WikiGraph"]


def _normalize(name: str) -> str:
    return name.strip().lower()


def _fact_key(f: Fact) -> str:
    return f"{f.head}|{f.relation}|{f.tail}"


def _schema_key(f: Fact) -> str:
    return f"{f.head_type}|{f.relation}|{f.tail_type}"


class WikiGraph:
    """Three-layer knowledge graph: entity → fact → passage, with schema layer.

    Vertex types: entity, fact, schema, passage.
    Edge types: entity→fact, fact→passage, fact→schema.
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = path
        if path and path.exists():
            self._g = ig.Graph.Read_GraphML(str(path))
        else:
            self._g = ig.Graph(directed=True)
            self._g.vs["kind"] = []
            self._g.vs["key"] = []

    def _find_vertex(self, kind: str, key: str) -> int | None:
        """Find vertex index by kind+key, or None."""
        for v in self._g.vs:
            if v["kind"] == kind and v["key"] == key:
                return v.index
        return None

    def _get_or_create(self, kind: str, key: str, **attrs: Any) -> int:
        """Ported from MemGraphRAG memory.py::_get_or_create_* pattern."""
        idx = self._find_vertex(kind, key)
        if idx is not None:
            return idx
        self._g.add_vertex(kind=kind, key=key, **attrs)
        return self._g.vcount() - 1

    def update(self, slug: str, facts: ExtractedFacts) -> None:
        """Add/replace facts for a page. Idempotent — removes old edges first."""
        self.remove_page(slug)

        passage_idx = self._get_or_create("passage", slug, slug=slug)

        for fact in facts.facts:
            fk = _fact_key(fact)
            sk = _schema_key(fact)

            fact_idx = self._get_or_create(
                "fact", fk,
                head=fact.head, relation=fact.relation, tail=fact.tail,
                head_type=fact.head_type, tail_type=fact.tail_type,
            )
            schema_idx = self._get_or_create(
                "schema", sk,
                head_type=fact.head_type, relation=fact.relation, tail_type=fact.tail_type,
            )

            # Entity nodes for head and tail
            head_idx = self._get_or_create(
                "entity", _normalize(fact.head), name=fact.head, entity_type=fact.head_type,
            )
            tail_idx = self._get_or_create(
                "entity", _normalize(fact.tail), name=fact.tail, entity_type=fact.tail_type,
            )

            # Edges: entity→fact, fact→passage, fact→schema
            self._add_edge_if_missing(head_idx, fact_idx)
            self._add_edge_if_missing(tail_idx, fact_idx)
            self._add_edge_if_missing(fact_idx, passage_idx)
            self._add_edge_if_missing(fact_idx, schema_idx)

        # Also add standalone entities (those without facts)
        for ent in facts.entities:
            self._get_or_create("entity", _normalize(ent.text), name=ent.text, entity_type=ent.entity_type)

    def _add_edge_if_missing(self, src: int, dst: int) -> None:
        if not self._g.are_connected(src, dst):
            self._g.add_edge(src, dst)

    def remove_page(self, slug: str) -> None:
        """Remove passage vertex and edges. Orphaned fact/entity vertices stay for now."""
        idx = self._find_vertex("passage", slug)
        if idx is None:
            return
        # Remove edges to/from this passage, then the vertex
        edges_to_delete = self._g.incident(idx, mode="all")
        self._g.delete_edges(edges_to_delete)
        self._g.delete_vertices(idx)

    def entity_lookup(self, entity_names: Sequence[str]) -> list[str]:
        """Return page slugs reachable from named entities (entity→fact→passage)."""
        slugs: list[str] = []
        for name in entity_names:
            eidx = self._find_vertex("entity", _normalize(name))
            if eidx is None:
                continue
            # entity → fact neighbors
            for fidx in self._g.neighbors(eidx, mode="out"):
                if self._g.vs[fidx]["kind"] != "fact":
                    continue
                # fact → passage neighbors
                for pidx in self._g.neighbors(fidx, mode="out"):
                    if self._g.vs[pidx]["kind"] != "passage":
                        continue
                    slug = self._g.vs[pidx]["key"]
                    if slug not in slugs:
                        slugs.append(slug)
        return slugs

    def ppr(
        self, seed_slugs: list[str], *, alpha: float = 0.85, top_k: int = 10
    ) -> list[tuple[str, float]]:
        """Personalized PageRank from seed passage nodes.

        Ported from MemGraphRAG Memgraphrag.retrieve PPR approach.
        """
        if not seed_slugs or self._g.vcount() == 0:
            return []

        reset = [0.0] * self._g.vcount()
        for slug in seed_slugs:
            idx = self._find_vertex("passage", slug)
            if idx is not None:
                reset[idx] = 1.0

        if sum(reset) == 0.0:
            return []

        scores = self._g.personalized_pagerank(
            reset=reset, damping=alpha, directed=False
        )

        passage_scores: list[tuple[str, float]] = []
        for v in self._g.vs:
            if v["kind"] == "passage":
                passage_scores.append((v["key"], scores[v.index]))

        passage_scores.sort(key=lambda x: -x[1])
        return passage_scores[:top_k]

    def rebuild(self, repo: Any) -> int:
        """Rebuild graph from page frontmatter. Returns vertex count."""
        from .protocols import Entity as E, Fact as F

        self._g = ig.Graph(directed=True)
        for page in repo.list_pages():
            entities_raw = page.frontmatter.get("entities", [])
            facts_raw = page.frontmatter.get("facts", [])
            entities = tuple(
                E(text=e["text"], entity_type=e["entity_type"]) for e in entities_raw
            )
            facts = tuple(
                F(
                    head=f["head"], relation=f["relation"], tail=f["tail"],
                    head_type=f["head_type"], tail_type=f["tail_type"],
                )
                for f in facts_raw
            )
            if entities or facts:
                self.update(page.slug, ExtractedFacts(entities=entities, facts=facts))
        return self._g.vcount()

    def save(self) -> None:
        if self._path is not None:
            self._g.write_graphml(str(self._path))

    @property
    def stats(self) -> dict[str, int]:
        counts: dict[str, int] = {"entities": 0, "facts": 0, "schemas": 0, "passages": 0, "edges": self._g.ecount()}
        for v in self._g.vs:
            kind = v["kind"]
            if kind == "entity":
                counts["entities"] += 1
            elif kind == "fact":
                counts["facts"] += 1
            elif kind == "schema":
                counts["schemas"] += 1
            elif kind == "passage":
                counts["passages"] += 1
        return counts
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/nandanthakur/projects/exale && uv run pytest packages/wiki-engine/tests/test_knowledge_graph.py -v`
Expected: All pass

- [ ] **Step 5: Write tests for GraphML persistence**

Append to `packages/wiki-engine/tests/test_knowledge_graph.py`:

```python
def test_save_and_load(tmp_path):
    path = tmp_path / "graph.graphml"
    g = WikiGraph(path=path)
    g.update("page-a", _sample_facts())
    g.save()

    assert path.exists()

    g2 = WikiGraph(path=path)
    assert g2.stats["passages"] == 1
    assert g2.stats["facts"] == 2
    assert g2.stats["entities"] == 3


def test_rebuild_from_repo(tmp_path):
    from wiki_engine.repo import WikiRepo
    from wiki_engine.page import Page

    repo = WikiRepo.init(tmp_path / "wiki", committer=lambda *_: None)
    repo.write_page(Page(
        slug="acme",
        frontmatter={
            "title": "Acme",
            "type": "source",
            "entities": [{"text": "Acme Corp", "entity_type": "ORG"}],
            "facts": [
                {"head": "Acme Corp", "relation": "acquired", "tail": "WidgetCo",
                 "head_type": "ORG", "tail_type": "ORG"},
            ],
        },
        body="Acme Corp acquired WidgetCo.\n",
    ))

    g = WikiGraph()
    count = g.rebuild(repo)
    assert count > 0
    assert g.stats["passages"] == 1
    assert g.stats["facts"] == 1
    slugs = g.entity_lookup(["Acme Corp"])
    assert "acme" in slugs
```

- [ ] **Step 6: Run to verify they pass**

Run: `cd /Users/nandanthakur/projects/exale && uv run pytest packages/wiki-engine/tests/test_knowledge_graph.py -v`
Expected: All pass

- [ ] **Step 7: Run full suite + lint**

Run: `cd /Users/nandanthakur/projects/exale && uv run pytest && uv run ruff check .`
Expected: All pass

- [ ] **Step 8: Commit**

```bash
git add packages/wiki-engine/src/wiki_engine/knowledge_graph.py packages/wiki-engine/tests/test_knowledge_graph.py
git commit -m "feat: WikiGraph — three-layer igraph knowledge graph with PPR"
```

---

## Task 5: Ingest Integration — Extract Facts During Ingest

**Files:**
- Modify: `packages/wiki-engine/src/wiki_engine/ingest.py`
- Modify: `packages/wiki-engine/tests/test_ingest.py`

- [ ] **Step 1: Write failing test for ingest with extraction**

Append to `packages/wiki-engine/tests/test_ingest.py`:

```python
def test_ingest_with_extractor_stores_facts_in_frontmatter(wiki_repo, default_schema):
    """When an extractor is provided, entities/facts appear in page frontmatter."""
    from wiki_engine.protocols import Entity, ExtractedFacts, Fact

    class StubExtractor:
        def extract(self, text: str) -> ExtractedFacts:
            return ExtractedFacts(
                entities=(Entity("Acme", "ORG"),),
                facts=(Fact("Acme", "acquired", "Widget", "ORG", "ORG"),),
            )

    source = Source(
        kind=SourceKind.MESSAGE, identifier="ext-test",
        text="Acme acquired Widget.", title="Acme News",
    )
    result = ingest(
        source, repo=wiki_repo, schema=default_schema,
        summarizer=FakeSummarizer(), extractor=StubExtractor(),
    )
    assert result.created
    page = wiki_repo.read_page(result.slug)
    assert len(page.frontmatter["entities"]) == 1
    assert page.frontmatter["entities"][0]["text"] == "Acme"
    assert len(page.frontmatter["facts"]) == 1
    assert page.frontmatter["facts"][0]["head"] == "Acme"


def test_ingest_without_extractor_has_no_facts(wiki_repo, default_schema):
    """Backward compat: no extractor means no entities/facts in frontmatter."""
    source = Source(
        kind=SourceKind.MESSAGE, identifier="no-ext",
        text="Plain text.", title="Plain",
    )
    result = ingest(
        source, repo=wiki_repo, schema=default_schema,
        summarizer=FakeSummarizer(),
    )
    assert result.created
    page = wiki_repo.read_page(result.slug)
    assert "entities" not in page.frontmatter
    assert "facts" not in page.frontmatter
```

Check the existing test fixtures. The test file likely already imports `Source`, `SourceKind`, `FakeSummarizer`, `ingest`, and has a `wiki_repo` fixture. Add the necessary imports if they don't exist.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/nandanthakur/projects/exale && uv run pytest packages/wiki-engine/tests/test_ingest.py::test_ingest_with_extractor_stores_facts_in_frontmatter -v`
Expected: `TypeError: ingest() got an unexpected keyword argument 'extractor'`

- [ ] **Step 3: Add extractor/graph params to ingest()**

In `packages/wiki-engine/src/wiki_engine/ingest.py`, update the import and signature:

Add to imports:
```python
from .protocols import Embedder, ExtractedFacts, FactExtractor, Summarizer
```

Change the `ingest()` signature to add two new optional params after `store`:

```python
def ingest(
    source: Source,
    *,
    repo: WikiRepo,
    schema: WikiSchema,
    summarizer: Summarizer,
    off_limits: Iterable[str] = (),
    date: str | None = None,
    embedder: Embedder | None = None,
    store: VectorStore | None = None,
    contributor: str | None = None,
    extractor: FactExtractor | None = None,
    graph: object | None = None,  # WikiGraph, but avoid circular import
) -> IngestResult:
```

After the `summary = summarizer.summarize(source)` line and the embedding line, add:

```python
    extracted = extractor.extract(summary) if extractor is not None else None
```

Inside the transaction block, after building `frontmatter` dict and before `page = Page(...)`, add:

```python
        if extracted is not None and (extracted.entities or extracted.facts):
            frontmatter["entities"] = [
                {"text": e.text, "entity_type": e.entity_type} for e in extracted.entities
            ]
            frontmatter["facts"] = [
                {
                    "head": f.head, "relation": f.relation, "tail": f.tail,
                    "head_type": f.head_type, "tail_type": f.tail_type,
                }
                for f in extracted.facts
            ]
```

After `store.upsert(slug, embedding)`, add:

```python
        if graph is not None and extracted is not None:
            graph.update(slug, extracted)  # type: ignore[union-attr]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/nandanthakur/projects/exale && uv run pytest packages/wiki-engine/tests/test_ingest.py -v`
Expected: All pass (new + existing tests)

- [ ] **Step 5: Run full suite**

Run: `cd /Users/nandanthakur/projects/exale && uv run pytest`
Expected: All pass, coverage >= 80%

- [ ] **Step 6: Commit**

```bash
git add packages/wiki-engine/src/wiki_engine/ingest.py packages/wiki-engine/tests/test_ingest.py
git commit -m "feat: extract facts during ingest, store in page frontmatter"
```

---

## Task 6: Retrieval Upgrade — Graph PPR + RRF Fusion

**Files:**
- Modify: `packages/wiki-engine/src/wiki_engine/retrieval.py`
- Create: `packages/wiki-engine/tests/test_retriever_graph.py`

- [ ] **Step 1: Write failing tests for graph-enhanced retrieval**

Create `packages/wiki-engine/tests/test_retriever_graph.py`:

```python
"""Tests for graph-enhanced retrieval with PPR and RRF fusion."""
import pytest
from wiki_engine.protocols import Entity, ExtractedFacts, Fact
from wiki_engine.fakes import FakeEmbedder, FakeFactExtractor
from wiki_engine.knowledge_graph import WikiGraph
from wiki_engine.page import Page
from wiki_engine.repo import WikiRepo
from wiki_engine.retrieval import InMemoryVectorStore, Retriever, reciprocal_rank_fusion


@pytest.fixture
def wiki_with_graph(tmp_path):
    """A wiki repo with two pages, a populated graph, and a vector store."""
    repo = WikiRepo.init(tmp_path / "wiki", committer=lambda *_: None)
    embedder = FakeEmbedder()
    store = InMemoryVectorStore()
    graph = WikiGraph()

    # Page A: Acme acquired WidgetCo
    page_a = Page(slug="acme-news", frontmatter={"title": "Acme News", "type": "source"}, body="Acme Corp acquired WidgetCo last quarter.\n")
    repo.write_page(page_a)
    store.upsert("acme-news", embedder.embed([page_a.body])[0])
    repo.write_index("# Index\n\n## General\n- [[Acme News]] (acme-news) — Acme Corp acquired WidgetCo\n")
    graph.update("acme-news", ExtractedFacts(
        entities=(Entity("Acme Corp", "ORG"), Entity("WidgetCo", "ORG")),
        facts=(Fact("Acme Corp", "acquired", "WidgetCo", "ORG", "ORG"),),
    ))

    # Page B: Bob works at Acme
    page_b = Page(slug="bob-profile", frontmatter={"title": "Bob Profile", "type": "source"}, body="Bob is an engineer at Acme Corp.\n")
    repo.write_page(page_b)
    store.upsert("bob-profile", embedder.embed([page_b.body])[0])
    graph.update("bob-profile", ExtractedFacts(
        entities=(Entity("Bob", "PERSON"), Entity("Acme Corp", "ORG")),
        facts=(Fact("Bob", "works_at", "Acme Corp", "PERSON", "ORG"),),
    ))

    return repo, store, embedder, graph


class EntityOnlyExtractor:
    """Extracts entities from question text (simulates spaCy at query time)."""
    def extract(self, text: str) -> ExtractedFacts:
        # Hardcoded for test: return "Acme Corp" if it appears in text
        entities = []
        if "Acme" in text or "acme" in text:
            entities.append(Entity("Acme Corp", "ORG"))
        if "Bob" in text or "bob" in text:
            entities.append(Entity("Bob", "PERSON"))
        return ExtractedFacts(entities=tuple(entities), facts=())


def test_retriever_with_graph_finds_related_pages(wiki_with_graph):
    repo, store, embedder, graph = wiki_with_graph
    extractor = EntityOnlyExtractor()
    retriever = Retriever(repo=repo, store=store, embedder=embedder, graph=graph, extractor=extractor)
    results = retriever.retrieve("What did Acme Corp acquire?", k=5)
    assert "acme-news" in results


def test_retriever_graph_finds_multi_hop(wiki_with_graph):
    """Graph PPR should surface bob-profile when querying about Acme (shared entity)."""
    repo, store, embedder, graph = wiki_with_graph
    extractor = EntityOnlyExtractor()
    retriever = Retriever(repo=repo, store=store, embedder=embedder, graph=graph, extractor=extractor)
    results = retriever.retrieve("Tell me about Acme Corp", k=5)
    assert "acme-news" in results
    assert "bob-profile" in results


def test_retriever_without_graph_falls_back(wiki_with_graph):
    """Without graph, retriever works the same as before (structural + vector)."""
    repo, store, embedder, _graph = wiki_with_graph
    retriever = Retriever(repo=repo, store=store, embedder=embedder)
    results = retriever.retrieve("Acme", k=5)
    assert isinstance(results, list)


def test_rrf_fusion():
    list_a = ["page-1", "page-2", "page-3"]
    list_b = ["page-2", "page-4", "page-1"]
    list_c = ["page-3", "page-1"]
    result = reciprocal_rank_fusion(list_a, list_b, list_c, k=3)
    # page-1 appears in all three lists, should rank highest
    assert result[0] == "page-1"
    assert len(result) == 3


def test_rrf_empty_lists():
    assert reciprocal_rank_fusion(k=3) == []
    assert reciprocal_rank_fusion([], [], k=3) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/nandanthakur/projects/exale && uv run pytest packages/wiki-engine/tests/test_retriever_graph.py -v`
Expected: `ImportError: cannot import name 'reciprocal_rank_fusion'`

- [ ] **Step 3: Add RRF function and graph-aware retrieval to retrieval.py**

In `packages/wiki-engine/src/wiki_engine/retrieval.py`:

Add to imports:
```python
from .protocols import Embedder, FactExtractor
```

Add the RRF function after the existing `cosine` function:

```python
def reciprocal_rank_fusion(*ranked_lists: list[str], k: int, rank_constant: int = 60) -> list[str]:
    """Merge multiple ranked lists via Reciprocal Rank Fusion (RRF)."""
    scores: dict[str, float] = {}
    for ranked in ranked_lists:
        for rank, slug in enumerate(ranked):
            scores[slug] = scores.get(slug, 0.0) + 1.0 / (rank_constant + rank)
    return sorted(scores, key=lambda s: scores[s], reverse=True)[:k]
```

Add `"reciprocal_rank_fusion"` to `__all__`.

Modify the `Retriever.__init__` signature:

```python
class Retriever:
    """Hybrid retrieval: structural + graph-PPR + vector, fused via RRF."""

    def __init__(
        self,
        *,
        repo: WikiRepo,
        store: VectorStore,
        embedder: Embedder,
        graph: object | None = None,
        extractor: FactExtractor | None = None,
    ) -> None:
        self._repo = repo
        self._store = store
        self._embedder = embedder
        self._graph = graph
        self._extractor = extractor
```

Replace the existing `retrieve` method:

```python
    def retrieve(self, question: str, *, k: int = 5) -> list[str]:
        """Structural hits + graph PPR + vector, fused via RRF when graph available."""
        structural = self.structural(question, k=k)
        query_vector = self._embedder.embed([question])[0]
        vector_slugs = [hit.slug for hit in self._store.search(query_vector, k)]

        if self._graph is not None and self._extractor is not None:
            graph_slugs = self._graph_retrieve(question, k=k)
            return reciprocal_rank_fusion(structural, graph_slugs, vector_slugs, k=k)

        merged = structural + [slug for slug in vector_slugs if slug not in structural]
        return merged[:k]

    def _graph_retrieve(self, question: str, *, k: int) -> list[str]:
        extracted = self._extractor.extract(question)  # type: ignore[union-attr]
        entity_names = [e.text for e in extracted.entities]
        if not entity_names:
            return []
        seeds = self._graph.entity_lookup(entity_names)  # type: ignore[union-attr]
        if not seeds:
            return []
        ranked = self._graph.ppr(seeds, top_k=k)  # type: ignore[union-attr]
        return [slug for slug, _score in ranked]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/nandanthakur/projects/exale && uv run pytest packages/wiki-engine/tests/test_retriever_graph.py -v`
Expected: All pass

- [ ] **Step 5: Run full suite to check existing retrieval tests still pass**

Run: `cd /Users/nandanthakur/projects/exale && uv run pytest`
Expected: All pass, coverage >= 80%

- [ ] **Step 6: Commit**

```bash
git add packages/wiki-engine/src/wiki_engine/retrieval.py packages/wiki-engine/tests/test_retriever_graph.py
git commit -m "feat: graph-PPR retrieval + reciprocal rank fusion"
```

---

## Task 7: Conflict Detection and Auto-Resolution

**Files:**
- Create: `packages/wiki-engine/src/wiki_engine/conflicts.py`
- Create: `packages/wiki-engine/tests/test_conflicts.py`
- Modify: `packages/wiki-engine/src/wiki_engine/fakes.py`

Ports from MemGraphRAG `resolve_conflict.py` + `prompt.py` conflict prompts.

- [ ] **Step 1: Write failing tests for conflict detection + resolution**

Create `packages/wiki-engine/tests/test_conflicts.py`:

```python
"""Tests for fact conflict detection and resolution."""
import json
import pytest
from wiki_engine.protocols import Entity, ExtractedFacts, Fact
from wiki_engine.knowledge_graph import WikiGraph
from wiki_engine.conflicts import detect_fact_contradictions, Conflict, Resolution
from wiki_engine.fakes import FakeConflictResolver


def _build_graph_with_conflict():
    g = WikiGraph()
    g.update("page-a", ExtractedFacts(
        entities=(Entity("Acme Corp", "ORG"),),
        facts=(Fact("Acme Corp", "ceo", "Alice", "ORG", "PERSON"),),
    ))
    g.update("page-b", ExtractedFacts(
        entities=(Entity("Acme Corp", "ORG"),),
        facts=(Fact("Acme Corp", "ceo", "Bob", "ORG", "PERSON"),),
    ))
    return g


def test_detect_finds_contradicting_facts():
    g = _build_graph_with_conflict()
    conflicts = detect_fact_contradictions(g)
    assert len(conflicts) >= 1
    c = conflicts[0]
    assert c.fact_a.head == "Acme Corp"
    assert c.fact_b.head == "Acme Corp"
    assert c.fact_a.tail != c.fact_b.tail


def test_detect_no_conflicts_when_different_relations():
    g = WikiGraph()
    g.update("page-a", ExtractedFacts(
        entities=(Entity("Acme Corp", "ORG"),),
        facts=(Fact("Acme Corp", "ceo", "Alice", "ORG", "PERSON"),),
    ))
    g.update("page-b", ExtractedFacts(
        entities=(Entity("Acme Corp", "ORG"),),
        facts=(Fact("Acme Corp", "cfo", "Bob", "ORG", "PERSON"),),
    ))
    conflicts = detect_fact_contradictions(g)
    assert len(conflicts) == 0


def test_detect_no_conflicts_same_tail():
    g = WikiGraph()
    g.update("page-a", ExtractedFacts(
        entities=(Entity("Acme Corp", "ORG"),),
        facts=(Fact("Acme Corp", "ceo", "Alice", "ORG", "PERSON"),),
    ))
    g.update("page-b", ExtractedFacts(
        entities=(Entity("Acme Corp", "ORG"),),
        facts=(Fact("Acme Corp", "ceo", "Alice", "ORG", "PERSON"),),
    ))
    conflicts = detect_fact_contradictions(g)
    assert len(conflicts) == 0


def test_fake_resolver_keeps_both():
    conflict = Conflict(
        fact_a=Fact("Acme Corp", "ceo", "Alice", "ORG", "PERSON"),
        fact_b=Fact("Acme Corp", "ceo", "Bob", "ORG", "PERSON"),
        conflict_type="mutual",
        page_a="page-a",
        page_b="page-b",
    )
    resolver = FakeConflictResolver()
    resolutions = resolver.resolve([conflict], repo=None)
    assert len(resolutions) == 1
    assert resolutions[0].action == "keep_both"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/nandanthakur/projects/exale && uv run pytest packages/wiki-engine/tests/test_conflicts.py -v`
Expected: `ModuleNotFoundError: No module named 'wiki_engine.conflicts'`

- [ ] **Step 3: Implement conflicts.py**

Create `packages/wiki-engine/src/wiki_engine/conflicts.py`:

```python
"""Fact conflict detection and auto-resolution.

Detection ported from MemGraphRAG resolve_conflict.py::find_triples_sharing_head_or_tail.
Resolution prompts ported from MemGraphRAG prompt.py::PROMPT['conflict_detection'] and
PROMPT['conflict_resolution'].
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Protocol

from .protocols import Fact

if TYPE_CHECKING:
    from .knowledge_graph import WikiGraph
    from .repo import WikiRepo

__all__ = [
    "Conflict",
    "ConflictResolver",
    "FakeConflictResolver",
    "HermesConflictResolver",
    "Resolution",
    "detect_fact_contradictions",
]

# Ported from MemGraphRAG prompt.py PROMPT['conflict_detection']
_CONFLICT_DETECTION_SYSTEM = """You are an expert fact checker. Given a target triple and a list of related triples.

Your task:
Detect whether target triple conflicts with any triple in the list of related triples, and classify conflicts into three types:
(1) mutual conflict (mutual exclusivity / one-to-one relations)
(2) Temporal conflict (time-dependent facts)
(3) Granularity conflict (different levels of specificity)

Output MUST be a valid JSON object with:
{"has_conflict": true/false, "conflict_type": "mutual"|"temporal"|"granularity"|null}"""

# Ported from MemGraphRAG prompt.py PROMPT['conflict_resolution']
_CONFLICT_RESOLUTION_SYSTEM = """You are an expert knowledge graph curator. Given conflicting triples and their source passages, resolve the conflicts.

Resolution strategies:
1. Mutual: keep the more accurate triple, discard the other.
2. Temporal: add time context if available, otherwise keep both.
3. Granularity: keep both if compatible (containment), otherwise keep the more specific.

Output a JSON object:
{"action": "keep_a"|"keep_b"|"modify_a"|"modify_b"|"keep_both", "reason": "explanation", "resolved_triple": ["head","relation","tail"] or null}"""


@dataclass(frozen=True)
class Conflict:
    fact_a: Fact
    fact_b: Fact
    conflict_type: Literal["mutual", "temporal", "granularity"]
    page_a: str
    page_b: str


@dataclass(frozen=True)
class Resolution:
    conflict: Conflict
    action: Literal["keep_a", "keep_b", "modify_a", "modify_b", "keep_both"]
    resolved_fact: Fact | None
    reason: str


class ConflictResolver(Protocol):
    def resolve(self, conflicts: list[Conflict], repo: WikiRepo | Any) -> list[Resolution]: ...


def _warn(msg: str) -> None:
    print(f"[wiki_engine.conflicts] {msg}", file=sys.stderr, flush=True)


def detect_fact_contradictions(graph: WikiGraph) -> list[Conflict]:
    """Find facts sharing head entity + relation but with different tails.

    Ported from MemGraphRAG resolve_conflict.py::find_triples_sharing_head_or_tail.
    """
    g = graph._g
    conflicts: list[Conflict] = []

    # Group facts by (head_entity_key, relation)
    head_rel_groups: dict[tuple[str, str], list[tuple[Fact, str]]] = defaultdict(list)

    for v in g.vs:
        if v["kind"] != "fact":
            continue
        fact = Fact(
            head=v["head"], relation=v["relation"], tail=v["tail"],
            head_type=v["head_type"], tail_type=v["tail_type"],
        )
        # Find which passage(s) this fact belongs to
        for pidx in g.neighbors(v.index, mode="out"):
            if g.vs[pidx]["kind"] == "passage":
                slug = g.vs[pidx]["key"]
                key = (fact.head.strip().lower(), fact.relation.strip().lower())
                head_rel_groups[key].append((fact, slug))

    for (_head, _rel), entries in head_rel_groups.items():
        if len(entries) < 2:
            continue
        # Compare pairs — different tails = conflict candidate
        seen: set[tuple[str, str]] = set()
        for i, (fa, pa) in enumerate(entries):
            for fb, pb in entries[i + 1:]:
                if fa.tail.strip().lower() == fb.tail.strip().lower():
                    continue
                pair_key = (min(fa.tail, fb.tail), max(fa.tail, fb.tail))
                if pair_key in seen:
                    continue
                seen.add(pair_key)
                conflicts.append(Conflict(
                    fact_a=fa, fact_b=fb, conflict_type="mutual",
                    page_a=pa, page_b=pb,
                ))

    return conflicts


class HermesConflictResolver:
    """Resolve conflicts via LLM. Ported from MemGraphRAG resolve_conflict.py."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def resolve(self, conflicts: list[Conflict], repo: WikiRepo | Any) -> list[Resolution]:
        resolutions: list[Resolution] = []
        for conflict in conflicts:
            body_a = ""
            body_b = ""
            if repo is not None:
                page_a = repo.read_page(conflict.page_a)
                page_b = repo.read_page(conflict.page_b)
                body_a = page_a.body if page_a else ""
                body_b = page_b.body if page_b else ""

            user_prompt = (
                f"Triple A: ({conflict.fact_a.head}, {conflict.fact_a.relation}, {conflict.fact_a.tail})\n"
                f"Source A: {body_a[:500]}\n\n"
                f"Triple B: ({conflict.fact_b.head}, {conflict.fact_b.relation}, {conflict.fact_b.tail})\n"
                f"Source B: {body_b[:500]}\n\n"
                f"Conflict type: {conflict.conflict_type}"
            )
            try:
                raw = self._client.complete(_CONFLICT_RESOLUTION_SYSTEM, user_prompt, max_tokens=400)
                parsed = json.loads(raw)
                action = parsed.get("action", "keep_both")
                reason = parsed.get("reason", "")
                resolved_triple_raw = parsed.get("resolved_triple")
                resolved_fact = None
                if resolved_triple_raw and len(resolved_triple_raw) == 3:
                    resolved_fact = Fact(
                        head=resolved_triple_raw[0],
                        relation=resolved_triple_raw[1],
                        tail=resolved_triple_raw[2],
                        head_type=conflict.fact_a.head_type,
                        tail_type=conflict.fact_a.tail_type,
                    )
                resolutions.append(Resolution(
                    conflict=conflict, action=action,
                    resolved_fact=resolved_fact, reason=reason,
                ))
            except Exception as exc:
                _warn(f"conflict resolution failed ({exc}); keeping both")
                resolutions.append(Resolution(
                    conflict=conflict, action="keep_both",
                    resolved_fact=None, reason=f"LLM error: {exc}",
                ))
        return resolutions
```

- [ ] **Step 4: Add FakeConflictResolver to fakes.py**

In `packages/wiki-engine/src/wiki_engine/fakes.py`, add:

```python
from .conflicts import Conflict, Resolution

class FakeConflictResolver:
    """Deterministic resolver: always keeps both (no LLM needed)."""

    def resolve(self, conflicts: list[Conflict], repo: object = None) -> list[Resolution]:
        return [
            Resolution(conflict=c, action="keep_both", resolved_fact=None, reason="fake resolver")
            for c in conflicts
        ]
```

Add `"FakeConflictResolver"` to `__all__`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /Users/nandanthakur/projects/exale && uv run pytest packages/wiki-engine/tests/test_conflicts.py -v`
Expected: All pass

- [ ] **Step 6: Run full suite + lint**

Run: `cd /Users/nandanthakur/projects/exale && uv run pytest && uv run ruff check .`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add packages/wiki-engine/src/wiki_engine/conflicts.py packages/wiki-engine/src/wiki_engine/fakes.py packages/wiki-engine/tests/test_conflicts.py
git commit -m "feat: fact conflict detection + HermesConflictResolver"
```

---

## Task 8: Lint Integration — fact_contradiction Rule

**Files:**
- Modify: `packages/wiki-engine/src/wiki_engine/lint.py`
- Modify: `packages/wiki-engine/tests/test_lint.py`

- [ ] **Step 1: Write failing test for fact_contradiction lint rule**

Append to `packages/wiki-engine/tests/test_lint.py`:

```python
def test_fact_contradiction_lint_rule(wiki_repo, default_schema):
    """fact_contradiction rule detects conflicting facts across pages."""
    from wiki_engine.knowledge_graph import WikiGraph
    from wiki_engine.protocols import Entity, ExtractedFacts, Fact

    graph = WikiGraph()
    graph.update("page-a", ExtractedFacts(
        entities=(Entity("Acme Corp", "ORG"),),
        facts=(Fact("Acme Corp", "ceo", "Alice", "ORG", "PERSON"),),
    ))
    graph.update("page-b", ExtractedFacts(
        entities=(Entity("Acme Corp", "ORG"),),
        facts=(Fact("Acme Corp", "ceo", "Bob", "ORG", "PERSON"),),
    ))

    from wiki_engine.lint import fact_contradiction
    violations = fact_contradiction(wiki_repo, default_schema, graph=graph)
    assert len(violations) >= 1
    assert violations[0].rule == "fact_contradiction"
```

Check what fixtures exist in the test file (likely `wiki_repo`, `default_schema`). Add imports as needed.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/nandanthakur/projects/exale && uv run pytest packages/wiki-engine/tests/test_lint.py::test_fact_contradiction_lint_rule -v`
Expected: `ImportError: cannot import name 'fact_contradiction' from 'wiki_engine.lint'`

- [ ] **Step 3: Add fact_contradiction rule to lint.py**

Add to `packages/wiki-engine/src/wiki_engine/lint.py`:

```python
def fact_contradiction(
    repo: WikiRepo, schema: WikiSchema, graph: object | None = None
) -> list[Violation]:
    """Find contradicting facts via the knowledge graph.

    Uses detect_fact_contradictions from conflicts.py (ported from MemGraphRAG).
    """
    if graph is None:
        return []

    from .conflicts import detect_fact_contradictions

    conflicts = detect_fact_contradictions(graph)
    violations: list[Violation] = []
    for c in conflicts:
        violations.append(Violation(
            rule="fact_contradiction",
            severity="warning",
            confidence=0.85,
            message=(
                f"Conflicting facts: ({c.fact_a.head}, {c.fact_a.relation}, {c.fact_a.tail}) "
                f"vs ({c.fact_b.head}, {c.fact_b.relation}, {c.fact_b.tail})"
            ),
            affected_pages=[c.page_a, c.page_b],
            suggested_action="resolve_conflict",
            metadata={
                "conflict_type": c.conflict_type,
                "fact_a": list(c.fact_a),
                "fact_b": list(c.fact_b),
            },
        ))
    return violations
```

In the `lint()` function, add the graph-based rule when available. Update the function signature to accept `graph`:

```python
def lint(
    repo: WikiRepo,
    schema: WikiSchema,
    min_confidence: float = 0.7,
    rules: list[Callable[[WikiRepo, WikiSchema], list[Violation]]] | None = None,
    embedder: Embedder | None = None,
    graph: object | None = None,
) -> list[Violation]:
```

In the default rules block, after the embedder-based rules, add:

```python
        if graph is not None:
            rules.append(lambda r, s: fact_contradiction(r, s, graph))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/nandanthakur/projects/exale && uv run pytest packages/wiki-engine/tests/test_lint.py -v`
Expected: All pass

- [ ] **Step 5: Run full suite**

Run: `cd /Users/nandanthakur/projects/exale && uv run pytest`
Expected: All pass, coverage >= 80%

- [ ] **Step 6: Commit**

```bash
git add packages/wiki-engine/src/wiki_engine/lint.py packages/wiki-engine/tests/test_lint.py
git commit -m "feat: fact_contradiction lint rule using knowledge graph"
```

---

## Task 9: MCP Server Wiring — ToolContext + New Tools

**Files:**
- Modify: `packages/wiki-engine/src/wiki_engine/mcp_server.py`
- Modify: `packages/wiki-engine/src/wiki_engine/__main__.py`
- Modify: `packages/wiki-engine/tests/test_main_server.py`

- [ ] **Step 1: Extend ToolContext with new fields**

In `packages/wiki-engine/src/wiki_engine/mcp_server.py`, update `ToolContext`:

```python
from .protocols import Answerer, Embedder, FactExtractor, Summarizer

@dataclass(frozen=True)
class ToolContext:
    """Bundled collaborators shared by every MCP tool handler."""
    repo: WikiRepo
    embedder: Embedder
    vectorstore: VectorStore
    answerer: Answerer
    summarizer: Summarizer | None = None
    extractor: FactExtractor | None = None
    graph: object | None = None  # WikiGraph
    conflict_resolver: object | None = None  # ConflictResolver
```

- [ ] **Step 2: Wire graph into existing retriever construction**

In `handle_wiki_query`, `handle_wiki_context`, `handle_wiki_search`, update the `Retriever` construction to pass `graph` and `extractor`. For example, in `handle_wiki_query`:

Find all lines constructing `Retriever(repo=repo, store=..., embedder=...)` in the file and add the graph/extractor params. The adapter functions pass `ctx.graph` and `ctx.extractor`.

Update `_query_adapter`:
```python
def _query_adapter(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    return handle_wiki_query(
        repo=ctx.repo, query=args["query"],
        file_as_new_page=args.get("file_as_new_page", False),
        vectorstore=ctx.vectorstore, embedder=ctx.embedder, answerer=ctx.answerer,
        graph=ctx.graph, extractor=ctx.extractor,
    )
```

Add `graph` and `extractor` params to `handle_wiki_query`, `handle_wiki_context`, `handle_wiki_search` function signatures and pass them to `Retriever(...)`.

- [ ] **Step 3: Add wiki_graph_stats tool**

Add handler:

```python
def handle_wiki_graph_stats(graph: object | None) -> dict[str, Any]:
    if graph is None:
        return {"available": False}
    return {"available": True, **graph.stats}  # type: ignore[union-attr]
```

Add adapter + Tool entry to `TOOLS`:

```python
def _graph_stats_adapter(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    return handle_wiki_graph_stats(graph=ctx.graph)

Tool(
    name="wiki_graph_stats",
    description="Return knowledge graph statistics (entity/fact/schema/passage counts).",
    input_schema={"type": "object", "properties": {}},
    handler=_graph_stats_adapter,
),
```

- [ ] **Step 4: Add wiki_resolve_conflicts tool**

Add handler:

```python
def handle_wiki_resolve_conflicts(
    repo: WikiRepo, graph: object | None, resolver: object | None,
) -> dict[str, Any]:
    if graph is None or resolver is None:
        return {"available": False, "resolved": []}
    from .conflicts import detect_fact_contradictions
    conflicts = detect_fact_contradictions(graph)
    if not conflicts:
        return {"available": True, "conflicts_found": 0, "resolved": []}
    resolutions = resolver.resolve(conflicts, repo)  # type: ignore[union-attr]
    return {
        "available": True,
        "conflicts_found": len(conflicts),
        "resolved": [
            {"action": r.action, "reason": r.reason,
             "fact_a": list(r.conflict.fact_a), "fact_b": list(r.conflict.fact_b)}
            for r in resolutions
        ],
    }
```

Add adapter + Tool entry.

- [ ] **Step 5: Update __main__.py startup to wire graph + extractor**

In `packages/wiki-engine/src/wiki_engine/__main__.py`, after existing setup, add:

```python
# Load knowledge graph if GraphML exists
graph = None
graph_path = repo.wiki_dir / "graph.graphml"
try:
    from .knowledge_graph import WikiGraph
    graph = WikiGraph(path=graph_path)
except Exception as exc:
    _warn(f"knowledge graph unavailable ({exc})")

# Construct extractor
extractor = None
try:
    from .extraction import SpacyNerLlmExtractor
    extractor = SpacyNerLlmExtractor(llm_client=client if client else None)
except ImportError:
    from .fakes import FakeFactExtractor
    extractor = FakeFactExtractor()

# Construct conflict resolver
conflict_resolver = None
try:
    from .conflicts import HermesConflictResolver
    if client:
        conflict_resolver = HermesConflictResolver(client)
except Exception:
    pass
```

Pass these into `ToolContext(... extractor=extractor, graph=graph, conflict_resolver=conflict_resolver)`.

- [ ] **Step 6: Run full suite + lint + type check**

Run: `cd /Users/nandanthakur/projects/exale && uv run pytest && uv run ruff check . && uv run pyright`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add packages/wiki-engine/src/wiki_engine/mcp_server.py packages/wiki-engine/src/wiki_engine/__main__.py
git commit -m "feat: MCP server wiring — graph stats + conflict resolution tools"
```

---

## Task 10: Backfill CLI — reindex_facts

**Files:**
- Create: `packages/wiki-engine/src/wiki_engine/reindex_facts.py`
- Create: `packages/wiki-engine/tests/test_reindex_facts.py`

- [ ] **Step 1: Write failing test**

Create `packages/wiki-engine/tests/test_reindex_facts.py`:

```python
"""Tests for the fact backfill CLI."""
import pytest
from wiki_engine.page import Page
from wiki_engine.repo import WikiRepo
from wiki_engine.fakes import FakeFactExtractor
from wiki_engine.reindex_facts import reindex_facts, ReindexFactsResult


@pytest.fixture
def wiki_repo(tmp_path):
    repo = WikiRepo.init(tmp_path / "wiki", committer=lambda *_: None)
    repo.write_page(Page(
        slug="page-a",
        frontmatter={"title": "Page A", "type": "source"},
        body="Acme Corp acquired WidgetCo.\n",
    ))
    repo.write_page(Page(
        slug="page-b",
        frontmatter={"title": "Page B", "type": "source"},
        body="Bob works at Acme Corp.\n",
    ))
    return repo


def test_reindex_facts_processes_all_pages(wiki_repo):
    result = reindex_facts(wiki_repo, extractor=FakeFactExtractor())
    assert result.processed == 2
    assert result.graph_vertices >= 0


def test_reindex_facts_skips_pages_with_existing_facts(wiki_repo):
    wiki_repo.write_page(Page(
        slug="page-a",
        frontmatter={"title": "Page A", "type": "source", "facts": [{"head": "X", "relation": "r", "tail": "Y", "head_type": "T", "tail_type": "T"}]},
        body="Acme Corp acquired WidgetCo.\n",
    ))
    result = reindex_facts(wiki_repo, extractor=FakeFactExtractor(), force=False)
    assert result.processed == 1  # only page-b processed


def test_reindex_facts_force_reprocesses_all(wiki_repo):
    wiki_repo.write_page(Page(
        slug="page-a",
        frontmatter={"title": "Page A", "type": "source", "facts": [{"head": "X", "relation": "r", "tail": "Y", "head_type": "T", "tail_type": "T"}]},
        body="Acme Corp acquired WidgetCo.\n",
    ))
    result = reindex_facts(wiki_repo, extractor=FakeFactExtractor(), force=True)
    assert result.processed == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/nandanthakur/projects/exale && uv run pytest packages/wiki-engine/tests/test_reindex_facts.py -v`
Expected: `ModuleNotFoundError: No module named 'wiki_engine.reindex_facts'`

- [ ] **Step 3: Implement reindex_facts.py**

Create `packages/wiki-engine/src/wiki_engine/reindex_facts.py`:

```python
"""Backfill CLI: extract facts for all pages and rebuild the knowledge graph.

    python -m wiki_engine.reindex_facts        # process all pages
    python -m wiki_engine.reindex_facts --force # re-extract even if facts exist
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from .knowledge_graph import WikiGraph
from .page import Page
from .protocols import FactExtractor
from .repo import WikiRepo

__all__ = ["ReindexFactsResult", "reindex_facts"]


@dataclass(frozen=True)
class ReindexFactsResult:
    processed: int
    graph_vertices: int


def reindex_facts(
    repo: WikiRepo,
    extractor: FactExtractor,
    *,
    graph_path: Path | None = None,
    force: bool = False,
) -> ReindexFactsResult:
    """Extract facts for all pages and rebuild the graph."""
    graph = WikiGraph(path=graph_path)
    processed = 0

    for page in repo.list_pages():
        if not force and page.frontmatter.get("facts"):
            continue

        extracted = extractor.extract(page.body)
        fm = dict(page.frontmatter)
        if extracted.entities:
            fm["entities"] = [
                {"text": e.text, "entity_type": e.entity_type} for e in extracted.entities
            ]
        if extracted.facts:
            fm["facts"] = [
                {"head": f.head, "relation": f.relation, "tail": f.tail,
                 "head_type": f.head_type, "tail_type": f.tail_type}
                for f in extracted.facts
            ]
        repo.write_page(Page(slug=page.slug, frontmatter=fm, body=page.body))

        if extracted.entities or extracted.facts:
            graph.update(page.slug, extracted)
        processed += 1

    graph.save()
    return ReindexFactsResult(processed=processed, graph_vertices=graph.stats["entities"] + graph.stats["facts"])


def main() -> None:  # pragma: no cover
    import argparse

    parser = argparse.ArgumentParser(description="Backfill fact extraction for all wiki pages")
    parser.add_argument("--force", action="store_true", help="Re-extract even if facts exist")
    args = parser.parse_args()

    repo = WikiRepo(Path(os.environ.get("WIKI_REPO_PATH", "wiki")))
    graph_path = repo.wiki_dir / "graph.graphml"

    try:
        from .extraction import SpacyNerLlmExtractor
        from .llm_backends import build_judgment

        summarizer, _answerer = build_judgment()
        client = getattr(summarizer, "_client", None)
        extractor: FactExtractor = SpacyNerLlmExtractor(llm_client=client)
    except ImportError:
        from .fakes import FakeFactExtractor
        extractor = FakeFactExtractor()
        print("[reindex_facts] spaCy not available; using FakeFactExtractor", file=sys.stderr)

    result = reindex_facts(repo, extractor, graph_path=graph_path, force=args.force)
    print(f"reindex_facts: processed {result.processed} page(s), {result.graph_vertices} graph vertices")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/nandanthakur/projects/exale && uv run pytest packages/wiki-engine/tests/test_reindex_facts.py -v`
Expected: All pass

- [ ] **Step 5: Run full suite + lint**

Run: `cd /Users/nandanthakur/projects/exale && uv run pytest && uv run ruff check .`
Expected: All pass, coverage >= 80%

- [ ] **Step 6: Commit**

```bash
git add packages/wiki-engine/src/wiki_engine/reindex_facts.py packages/wiki-engine/tests/test_reindex_facts.py
git commit -m "feat: reindex_facts backfill CLI for existing wiki repos"
```

---

## Task 11: Exports + Final Verification

**Files:**
- Modify: `packages/wiki-engine/src/wiki_engine/__init__.py`

- [ ] **Step 1: Update __init__.py exports**

Add the new public names to `packages/wiki-engine/src/wiki_engine/__init__.py`:

```python
from .conflicts import Conflict, Resolution, detect_fact_contradictions
from .extraction import SpacyNerLlmExtractor
from .knowledge_graph import WikiGraph
from .reindex_facts import ReindexFactsResult, reindex_facts
```

Add them to `__all__` if used.

- [ ] **Step 2: Run full verification gate**

Run all four checks:

```bash
cd /Users/nandanthakur/projects/exale
uv run pytest                    # tests + 80% coverage gate
uv run ruff check .              # lint
uv run ruff format --check .     # format
uv run pyright                   # type check
```

Expected: All four pass with zero errors.

- [ ] **Step 3: Fix any issues found**

Address any failures from Step 2. Common issues:
- Missing type stubs for igraph → add `# type: ignore[import-untyped]` on the igraph import
- Coverage dip → ensure new modules have test coverage

- [ ] **Step 4: Commit**

```bash
git add packages/wiki-engine/src/wiki_engine/__init__.py
git commit -m "feat: export knowledge graph, extraction, conflicts from wiki_engine"
```

- [ ] **Step 5: Final commit summary**

Run: `git log --oneline feat/shared-context-layer --not main`

Verify the commit history tells a clean story.
