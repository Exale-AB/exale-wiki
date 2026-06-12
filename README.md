# Exale Wiki

The **Self-Improving Knowledge Wiki** — a pure-Python engine extracted from the Exale
platform monorepo. The wiki is plain markdown inside each customer's isolated seat,
organised in three layers (`raw/` sources, `wiki/` pages, `schema/` rulebook) with
three core operations (ingest / query / lint) and a knowledge-graph layer for
entity-aware retrieval and conflict detection.

**269 tests · 89.5% coverage · Python 3.11 · ruff + pyright clean**

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    MCP Server (JSON-RPC)                │
│  wiki_query · wiki_ingest · wiki_lint · wiki_context    │
│  wiki_search · wiki_get · wiki_graph_stats              │
│  wiki_resolve_conflicts                                 │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ┌───────────┐  ┌───────────┐  ┌──────────────────┐    │
│  │  Ingest   │  │   Query   │  │       Lint       │    │
│  │           │  │           │  │  (pluggable rules │    │
│  │ NER + LLM │  │ 3-signal  │  │   + conflict     │    │
│  │ extraction│  │   RRF     │  │   detection)     │    │
│  └─────┬─────┘  └─────┬─────┘  └──────────────────┘    │
│        │              │                                  │
│  ┌─────▼──────────────▼──────────────────────────┐      │
│  │            Hybrid Retrieval                   │      │
│  │  structural + graph-PPR + vector (RRF merge)  │      │
│  └─────┬──────────────┬──────────────┬───────────┘      │
│        │              │              │                   │
│  ┌─────▼─────┐  ┌─────▼─────┐  ┌────▼──────┐           │
│  │ WikiRepo  │  │ WikiGraph │  │VectorStore│           │
│  │ (markdown │  │ (igraph   │  │(pgvector/ │           │
│  │  + git)   │  │  GraphML) │  │ in-memory)│           │
│  └───────────┘  └───────────┘  └───────────┘           │
│                                                         │
├─────────────────────────────────────────────────────────┤
│  Protocols (DI seams):                                  │
│  Summarizer · Embedder · Answerer · FactExtractor       │
│  Hermes-backed at runtime, deterministic fakes in tests │
└─────────────────────────────────────────────────────────┘
```

### Dependency-injection seam (the central design)

The engine owns **deterministic bookkeeping**; **judgment** steps are injected as
`Protocol`s in `protocols.py`:

| Protocol | Used by | Injected at runtime via |
|----------|---------|------------------------|
| `Summarizer` | ingest | Hermes LLM proxy |
| `Embedder` | vector index | fastembed / Hermes |
| `Answerer` | query | Hermes LLM proxy |
| `FactExtractor` | ingest (NER + relations) | spaCy + Hermes LLM |

Tests inject deterministic fakes (`fakes.py`). The engine never calls an LLM API directly.

### Three-layer memory (MemGraphRAG-inspired)

Inspired by the [MemGraphRAG](https://arxiv.org/abs/2312.00216) (KDD 2026) architecture:

| Layer | Storage | Purpose |
|-------|---------|---------|
| **Schema** | `schema/AGENTS.md` (YAML frontmatter) | Ontology: allowed kinds, categories, honesty rules |
| **Fact** | Page frontmatter `entities:` / `facts:` + `WikiGraph` (igraph GraphML) | Entity triples (head, relation, tail) extracted via NER + LLM |
| **Passage** | `wiki/` pages + `raw/` sources | Verbatim text chunks, git-versioned markdown |

### Hybrid retrieval with Reciprocal Rank Fusion

Three ranked signals merged via RRF (`score = Σ 1/(60 + rank)`):

1. **Structural** — token overlap over the index catalog + wikilink neighbours
2. **Graph-PPR** — Personalized PageRank from seed passage nodes in the knowledge graph
3. **Vector** — cosine similarity via pgvector (or in-memory for tests)

### Knowledge graph

`WikiGraph` (igraph-backed, persisted as GraphML) with four vertex types:
`entity`, `fact`, `schema`, `passage`. Supports conflict detection (grouping facts
by normalised `(head, relation)` to find contradictory tails) and Personalized
PageRank for graph-enhanced retrieval.

## Packages

| Package | What it owns |
|---------|--------------|
| [`wiki-engine`](packages/wiki-engine) | Core: repo model, ingest, hybrid retrieval (structural + graph-PPR + pgvector), query, lint, schema enforcement, NER/fact extraction, knowledge graph, conflict detection, HTML render, MCP server (8 tools). No Hermes import. |
| [`wiki-utils`](packages/wiki-utils) | `log_action` logging helpers used by seat skill bundles. |
| [`wiki-validation`](packages/wiki-validation) | Least-privilege scope checks for seat skill bundles. |

### Optional extras

```
pip install wiki-engine[llm]         # openai SDK for Hermes proxy
pip install wiki-engine[embed]       # fastembed for local embeddings
pip install wiki-engine[extraction]  # spaCy for NER-based fact extraction
```

## Development

This is a [uv](https://docs.astral.sh/uv/) workspace. Python is pinned to **3.11**
to match the Hermes runtime.

```bash
uv sync                      # install all members + dev deps into shared .venv
uv run pytest                # full suite with the 80% coverage gate (enforced)
uv run ruff check .          # lint
uv run ruff format .         # format
uv run pyright               # type-check
```

Dev-tool pins are exact (`ruff==0.15.17`, `pyright==1.1.410`) so output is stable
across machines.

## MCP server

`python -m wiki_engine` runs a stdin/stdout JSON-RPC loop exposing 8 tools:

| Tool | Purpose |
|------|---------|
| `wiki_ingest` | Ingest a source → summary page + index/log updates |
| `wiki_query` | Hybrid retrieval → formatted context with citations |
| `wiki_lint` | Self-improvement: pluggable lint rules + conflict detection |
| `wiki_context` | Return raw context for a topic |
| `wiki_search` | Search the wiki index |
| `wiki_get` | Read a specific page by slug |
| `wiki_graph_stats` | Knowledge graph vertex/edge counts |
| `wiki_resolve_conflicts` | Detect contradictory facts in the graph |

Register with Hermes:

```bash
hermes mcp add wiki-engine --command /path/to/wiki-mcp-server.sh
hermes mcp test wiki-engine
```

The MCP server wires `FakeEmbedder` + `FakeVectorStore` by default —
structural-only retrieval, no database needed. For full hybrid retrieval,
configure `WIKI_DB_URL` and the `[embed]` extra.

## Local deployment

Native setup (no Docker):

- **Postgres 16** on `:5432`, database `wiki`, pgvector extension
- **Hermes** (native binary) serves the MCP; all three packages installed editable
  in the Hermes venv (`~/.hermes/hermes-agent/venv`)
- Provision a seat: `bash <seat>/.exale-local/setup.sh` (idempotent)
- Verify: `hermes mcp test wiki-engine`

## Constraints

- **All LLM calls route through Hermes** — no direct LLM API calls. The engine takes
  injected `Protocol` implementations so callers wire the Hermes-backed backends.
- **EU data residency only.**
- **Boring stack, on purpose:** Hermes (self-hosted), Postgres + pgvector. No Kubernetes.
