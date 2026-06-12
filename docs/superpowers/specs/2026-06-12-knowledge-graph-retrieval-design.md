# Knowledge Graph Retrieval — Design Spec

**Date:** 2026-06-12
**Branch:** `feat/shared-context-layer`
**Status:** Approved

Adds a three-layer knowledge graph (inspired by MemGraphRAG, KDD 2026) to the
wiki-engine's retrieval pipeline. Structured facts become first-class retrieval
handles alongside the existing structural (token overlap + wikilinks) and vector
(cosine similarity) paths.

## Goals

1. Extract entity/relation triples from ingested pages (hybrid spaCy NER + LLM).
2. Build a persistent knowledge graph (igraph + GraphML) with entity, fact,
   schema, and passage layers.
3. Upgrade retrieval with entity-aware graph traversal and Personalized PageRank.
4. Detect and auto-resolve fact contradictions via LLM.
5. Provide a backfill CLI for existing wiki repos.

## Non-Goals

- Replacing the existing structural or vector retrieval paths (they remain).
- Adding a graph database (Postgres adjacency, Neo4j). GraphML in the repo is
  sufficient.
- Real-time streaming extraction (extraction is per-ingest, batch via backfill).

## Constraints

- All LLM calls route through Hermes (OpenAI-compatible proxy). No direct vendor
  API calls.
- Python 3.11 (Hermes runtime pin).
- Markdown remains the system of record. The graph is derived and rebuildable.
- 80% test coverage gate must remain green.

---

## 1. Data Model

### 1.1 Page Frontmatter Extension

Pages gain two new optional frontmatter fields:

```yaml
entities:
  - text: "Acme Corp"
    entity_type: "ORG"
  - text: "WidgetCo"
    entity_type: "ORG"
  - text: "Jane Smith"
    entity_type: "PERSON"
facts:
  - head: "Acme Corp"
    relation: "acquired"
    tail: "WidgetCo"
    head_type: "ORG"
    tail_type: "ORG"
  - head: "Jane Smith"
    relation: "announced"
    tail: "Acme Corp"
    head_type: "PERSON"
    tail_type: "ORG"
```

Both fields are lists of dicts. When absent, the page has no extracted knowledge
and retrieval falls back to structural + vector.

### 1.2 Knowledge Graph (GraphML)

Stored at `wiki/graph.graphml`. Git-versioned. Rebuildable from page frontmatter.

**Vertex types:**

| Type | Key | Attributes |
|------|-----|-----------|
| `entity` | normalized name | `name`, `entity_type` |
| `fact` | `"head\|relation\|tail"` | `head`, `relation`, `tail`, `head_type`, `tail_type` |
| `schema` | `"head_type\|relation\|tail_type"` | `head_type`, `relation`, `tail_type`, `frequency` |
| `passage` | page slug | `slug` |

**Edge types:**

| From | To | Meaning |
|------|----|---------|
| `entity` | `fact` | entity participates in this triple |
| `fact` | `passage` | triple was extracted from this page |
| `fact` | `schema` | triple instantiates this ontology pattern |

---

## 2. Extraction Pipeline

### 2.1 Protocol

New in `protocols.py`:

```python
class Entity(NamedTuple):
    text: str
    entity_type: str   # "ORG", "PERSON", "DATE", etc.

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

### 2.2 Hybrid Implementation (`extraction.py`)

`SpacyNerLlmExtractor`:

1. **NER (no LLM cost):** spaCy `en_core_web_sm` extracts named entities from
   the summary text. Entities are deduplicated and filtered (exclude CARDINAL,
   ORDINAL, MONEY, PERCENT, QUANTITY — following MemGraphRAG's filter list).
2. **Relation extraction (one LLM call):** Entities + summary text sent to
   Hermes via `OpenAICompatibleClient`. Prompt adapted from MemGraphRAG's
   `RELATION_EXTRACTION_SYSTEM_PROMPT`. Returns JSON array of triples.

**Degradation chain:**

| spaCy | LLM | Result |
|-------|-----|--------|
| available | reachable | Full hybrid: entities + relations |
| available | down | Entities only (no relations) |
| unavailable | any | `FakeFactExtractor` (empty result) |

### 2.3 Integration with `ingest()`

New optional parameters: `extractor: FactExtractor | None`, `graph: WikiGraph | None`.

```
summarize(source)          # existing, outside lock
extract(summary)           # NEW, outside lock (LLM call)
embed(summary)             # existing, outside lock

with repo.transaction():   # existing lock boundary
    write raw + page       # existing (frontmatter now includes entities/facts)
    graph.update(slug, facts)  # NEW
    store.upsert(slug, emb)    # existing
    catalog + log          # existing
```

### 2.4 Dependency

spaCy is optional:

```toml
[project.optional-dependencies]
extraction = ["spacy>=3.7"]
```

The `en_core_web_sm` model is downloaded separately via `python -m spacy download en_core_web_sm`.

igraph is required:

```toml
[project.dependencies]
igraph = ">=0.11"
```

---

## 3. Knowledge Graph Module (`knowledge_graph.py`)

### 3.1 `WikiGraph` class

```python
class WikiGraph:
    def __init__(self, path: Path | None = None):
        """Load from GraphML or create empty."""

    def update(self, slug: str, facts: ExtractedFacts) -> None:
        """Add/replace facts for a page. Idempotent."""

    def remove_page(self, slug: str) -> None:
        """Remove passage vertex and orphaned fact/entity vertices."""

    def entity_lookup(self, entity_names: Sequence[str]) -> list[str]:
        """Return page slugs connected to any named entities."""

    def ppr(self, seed_slugs: list[str], *, alpha: float = 0.85, top_k: int = 10) -> list[tuple[str, float]]:
        """Personalized PageRank from seed passage nodes."""

    def find_entity_conflicts(self, entity: str) -> list[tuple[Fact, Fact, str]]:
        """Find fact pairs sharing an entity with same relation but different tails."""

    def rebuild(self, repo: WikiRepo) -> int:
        """Rebuild from page frontmatter. Returns vertex count."""

    def save(self) -> None:
        """Write to GraphML."""

    @property
    def stats(self) -> dict[str, int]:
        """Counts of each vertex/edge type."""
```

### 3.2 Vertex Deduplication

Entities are normalized (lowercased, stripped) before lookup. Facts are keyed
by `"head|relation|tail"`. Schemas by `"head_type|relation|tail_type"`. This
mirrors MemGraphRAG's `_get_or_create_*` pattern.

### 3.3 PPR Details

Uses `igraph.Graph.personalized_pagerank(reset=reset_vector, damping=0.85)` where
`reset_vector` is a list with 1.0 for seed passage vertices and 0.0 elsewhere.
Returns only passage-type vertices, sorted by score descending.

---

## 4. Retrieval Upgrade

### 4.1 Three-Signal Fusion

```
Question
    ├── STRUCTURAL: token overlap on catalog + 1-hop wikilinks
    ├── GRAPH-PPR:  NER on question → entity_lookup → PPR → ranked slugs
    └── VECTOR:     cosine similarity on page embeddings

    → Reciprocal Rank Fusion (RRF) → top-k slugs
```

### 4.2 Reciprocal Rank Fusion

```python
def _fuse(*ranked_lists: list[str], k: int, rank_constant: int = 60) -> list[str]:
    scores: dict[str, float] = {}
    for ranked in ranked_lists:
        for rank, slug in enumerate(ranked):
            scores[slug] = scores.get(slug, 0.0) + 1.0 / (rank_constant + rank)
    return sorted(scores, key=scores.get, reverse=True)[:k]
```

Standard RRF constant of 60. No tunable weights needed.

### 4.3 Retriever Changes

`Retriever.__init__` gains `graph: WikiGraph | None = None` and
`extractor: FactExtractor | None = None`. When both are `None`, behavior is
identical to today.

`_graph_retrieve(question, k)`:
1. `extractor.extract(question)` — spaCy NER only (no LLM, fast)
2. `graph.entity_lookup(entity_names)` — find seed pages
3. `graph.ppr(seeds, top_k=k)` — rank by graph proximity

---

## 5. Conflict Detection and Auto-Resolution

### 5.1 Detection (`conflicts.py`)

New lint rule `fact_contradiction`:

1. For each entity in the graph, find all facts where it appears as head.
2. Group by relation.
3. Within each group, pairs with different tails are conflict candidates.
4. Embed fact strings, filter by similarity > 0.7 (cheap noise filter).
5. Classify conflict type (mutual / temporal / granularity) via LLM.

### 5.2 Resolution Protocol

```python
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
    def resolve(self, conflicts: list[Conflict], repo: WikiRepo) -> list[Resolution]: ...
```

### 5.3 `HermesConflictResolver`

Sends conflicts + source page bodies to Hermes. Prompt adapted from
MemGraphRAG's `conflict_resolution` prompt. Returns JSON with keep/discard/modify
decisions.

Resolution applies:
- Modifies page frontmatter facts (remove discarded, replace modified)
- Updates the graph
- Each resolution is a separate git commit for auditability

### 5.4 MCP Tool

`wiki_resolve_conflicts`: runs detection, then resolution. Returns list of
actions taken. Exposed to agents so they can trigger resolution on demand.

---

## 6. Backfill Migration

### 6.1 CLI: `reindex_facts`

```bash
python -m wiki_engine.reindex_facts      # process all pages
python -m wiki_engine.reindex_facts --force  # re-extract even if facts exist
```

Iterates `repo.list_pages()`, runs `extractor.extract(page.body)`, writes
entities/facts into frontmatter, then `graph.rebuild()` + `graph.save()`.
Single commit at end.

Reuses:
- `WikiRepo.list_pages()` + `WikiRepo.transaction()`
- `SpacyNerLlmExtractor.extract()`
- `WikiGraph.rebuild()`

---

## 7. MCP Server Changes

### 7.1 `ToolContext` Extension

```python
@dataclass(frozen=True)
class ToolContext:
    repo: WikiRepo
    embedder: Embedder
    vectorstore: VectorStore
    answerer: Answerer
    summarizer: Summarizer | None = None
    extractor: FactExtractor | None = None
    graph: WikiGraph | None = None
    conflict_resolver: ConflictResolver | None = None
```

### 7.2 New Tools

| Tool | Description |
|------|-------------|
| `wiki_resolve_conflicts` | Detect + auto-resolve fact contradictions |
| `wiki_graph_stats` | Return graph vertex/edge counts and top schemas |

### 7.3 Startup Wiring (`__main__.py`)

1. Load `WikiGraph` from `wiki/graph.graphml` if exists
2. Construct `SpacyNerLlmExtractor` if spaCy importable, else `FakeFactExtractor`
3. Construct `HermesConflictResolver` if LLM available, else `FakeConflictResolver`
4. Pass into `ToolContext`

---

## 8. File Change Summary

| File | Change | Est. lines |
|------|--------|-----------|
| `protocols.py` | Add `FactExtractor`, `Entity`, `Fact`, `ExtractedFacts` | +30 |
| `fakes.py` | Add `FakeFactExtractor`, `FakeConflictResolver` | +25 |
| **`knowledge_graph.py`** | **NEW** | ~220 |
| **`extraction.py`** | **NEW** | ~150 |
| **`conflicts.py`** | **NEW** | ~180 |
| **`reindex_facts.py`** | **NEW** | ~60 |
| `ingest.py` | Add `extractor`/`graph` params | +25 |
| `retrieval.py` | PPR path + RRF fusion | +60 |
| `lint.py` | Wire `fact_contradiction` | +10 |
| `mcp_server.py` | Extend context, add 2 tools | +80 |
| `__main__.py` | Wire new components at startup | +30 |
| `pyproject.toml` | Add dependencies | +5 |
| Tests (8-10 files) | New + updated | ~600 |

**Total:** ~870 lines production, ~600 lines tests.

---

## 9. Sprint Plan

| Sprint | Focus | Depends on | Deliverables |
|--------|-------|-----------|-------------|
| **S1** | Data model + extraction | -- | `protocols.py`, `extraction.py`, `fakes.py`, tests |
| **S2** | Knowledge graph | S1 (dataclasses only) | `knowledge_graph.py`, `reindex_facts.py`, tests |
| **S3** | Retrieval upgrade | S1 + S2 | `retrieval.py` changes, MCP wiring, tests |
| **S4** | Conflicts + polish | S1 + S2 | `conflicts.py`, MCP tool, lint integration, tests |

S3 and S4 are independent of each other once S2 lands.

---

## 10. MemGraphRAG Reuse Map

Maximize reuse from `github.com/XMUDeepLIT/MemGraphRAG`. Port code directly
where possible; adapt only where our DI seam pattern or markdown-native storage
requires it.

### Direct ports (copy + adapt)

| MemGraphRAG file | What to port | Our target file | Adaptation needed |
|-----------------|-------------|----------------|-------------------|
| `src/prompt.py` | `RELATION_EXTRACTION_SYSTEM_PROMPT`, `RELATION_EXTRACTION_USER_PROMPT_TEMPLATE`, `PROMPT['conflict_detection']`, `PROMPT['conflict_resolution']` | `extraction.py`, `conflicts.py` | Minimal — change output parsing to match our `Fact` NamedTuple |
| `src/memory.py` | `SchemaNode`, `FactNode`, `PassageNode` dataclasses, `_get_or_create_schema/fact/passage` dedup logic, `build_from_openie_results` traversal pattern | `knowledge_graph.py` | Adapt from parallel-list storage to igraph vertices; dedup logic reused almost verbatim |
| `src/entity_type_extract.py` | `EntityExtractor` class — chunking + spaCy NER + entity filtering (excluded labels set) | `extraction.py` | Remove file I/O; wire to our `FactExtractor` protocol; run on summary text not raw chunks |
| `src/schema_fact_extract.py` | `RelationExtractor.extract_relations_from_chunk()`, `ChunkWithEntities`, `TripleWithSchema` dataclasses, entity filtering logic | `extraction.py` | Replace `LLMClient` with our `OpenAICompatibleClient`; map `RelationTriple` to our `Fact` |
| `src/resolve_conflict.py` | `detect_triple_conflicts()` — entity grouping + embedding similarity filter + LLM classification; resolution flow | `conflicts.py` | Replace their embedding model with our `Embedder` protocol; replace their LLM client with `OpenAICompatibleClient` |
| `src/ontology_filtering.py` | Low-frequency ontology pruning logic | `knowledge_graph.py` | Port as `WikiGraph._prune_rare_schemas(min_frequency)` |

### Structural reuse (pattern, not code)

| MemGraphRAG pattern | Our usage |
|--------------------|-----------|
| `Memgraphrag.retrieve()` — fact scoring → PPR → dense fallback | `Retriever._graph_retrieve()` — same flow, using igraph PPR |
| `EmbeddingStore` — hash-based dedup, parquet persistence | Not needed (page slugs are natural keys, pgvector handles persistence) |
| `Memgraphrag.build_graph()` — igraph construction with entity/fact/passage nodes | `WikiGraph.rebuild()` — same vertex/edge types, GraphML persistence |
| Three-layer bidirectional traversal (`get_facts_by_passage`, etc.) | igraph neighbor queries (more efficient than index lists) |

### Not reused

| Component | Reason |
|-----------|--------|
| `llm_client.py` (SQLite cache, httpx client) | We have `OpenAICompatibleClient` via Hermes; caching belongs in Hermes layer |
| `prompt_builder.py` | Simple string formatting; our prompts are inline constants |
| `embedding_model/` | We have `Embedder` protocol + `FakeEmbedder` / pgvector |
| `evaluation/` | Benchmark-specific; not applicable to per-seat wiki |
| `rerank.py` (DSPyFilter) | Adds DSPy dependency; RRF fusion is simpler and sufficient |
