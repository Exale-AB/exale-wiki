---
id: T05
title: Wire real semantic retrieval (embedder + pgvector) into the MCP
phase: 2
priority: P1
status: done
depends_on: [T06]
effort: L
risk: med
files:
  - packages/wiki-engine/src/wiki_engine/embed_backends.py  # new
  - packages/wiki-engine/src/wiki_engine/__main__.py
  - packages/wiki-engine/src/wiki_engine/mcp_server.py
  - packages/wiki-engine/pyproject.toml
  - packages/wiki-engine/tests/test_embed_backends.py       # new
---

# T05 — Semantic retrieval

## Problem (verified)
The deployed MCP wires `FakeEmbedder` (zero vectors) + `FakeVectorStore` (returns
nothing), and `handle_wiki_ingest` calls `ingest(...)` **without** an embedder/store,
so vectors are **never built**. Retrieval is therefore structural-only (token
overlap on `index.md` titles/summaries + wikilink neighbours). `PgVectorStore` and
the hybrid merge in `Retriever.retrieve` **already exist** — they're just wired to
fakes. A workflow asking *"how do we handle renewals?"* misses a page titled
*"Account lifecycle"* unless words literally overlap. Semantic recall is the core of
a context layer.

## Key decision — embeddings source
Nous (the configured chat provider) does **not** serve embeddings. Pick one:
- **(A, recommended) Local embedding model in-process** — e.g. `fastembed`
  (ONNX, `BAAI/bge-small-en-v1.5`, dim 384) or `sentence-transformers`. No external
  call, EU-residency-friendly, free, fast. Declare under a `[embed]` extra.
- **(B) Embeddings endpoint** — only if a configured provider exposes
  `/v1/embeddings`; reuse the OpenAI-compatible client pattern from `llm_backends.py`.

Default to (A). Record the choice + model + dim in the Status log.

## Goal / acceptance
- On `wiki_ingest`, the page summary is embedded and upserted to the vector store.
- `wiki_query` / `wiki_context` return semantically-related pages that share **no
  literal tokens** with the query.
- DB or embedder unavailable → **graceful fallback** to structural-only
  (FakeEmbedder + FakeVectorStore), logged to stderr; the MCP never crashes.

## Design
1. `embed_backends.py`:
   - `LocalEmbedder(Embedder)` (option A) wrapping the chosen model; `embed(texts) ->
     list[list[float]]`. Config: `WIKI_EMBED_MODEL`, `WIKI_EMBED_DIM`.
   - `build_retrieval() -> tuple[Embedder, VectorStore]`: construct `LocalEmbedder`
     + `PgVectorStore(dsn=os.environ["WIKI_DB_URL" or "DATABASE_URL"], dim=DIM)`,
     call `ensure_schema()`; on any failure return `FakeEmbedder()`,
     `FakeVectorStore()` with a `_warn`. Mirror the `build_judgment()` pattern.
2. `__main__.main`: replace the hard-coded fakes with `embedder, vectorstore =
   build_retrieval()`.
3. `mcp_server.handle_wiki_ingest`: accept `embedder`/`store` and pass them to
   `ingest(...)` so vectors are written on ingest. Thread them from
   `handle_request` (already has `embedder`, `vectorstore`).
4. `pyproject.toml`: add `[project.optional-dependencies] embed = ["fastembed>=0.3"]`
   (or chosen lib). Seat installs `wiki-engine[llm,embed]`.

## Test plan (TDD)
`tests/test_embed_backends.py` (no network/DB — use `InMemoryVectorStore` + a
deterministic stub embedder):
- `test_ingest_then_query_finds_semantic_neighbour` — two pages with disjoint
  vocabularies but near vectors (stub embedder maps them close); query retrieves the
  non-lexical match via the vector path.
- `test_build_retrieval_falls_back_when_store_unavailable` — monkeypatch
  `PgVectorStore` construction to raise → returns fakes.
- Keep `test_pgvector_unit.py` SQL assertions intact.

## Verification
```bash
uv run pytest packages/wiki-engine/tests/ -k "embed or retriev or vector" -v
uv run pytest
```
Integration (native PG on :5432, `wiki` DB): run T06 reindex, then a semantic query
through the launcher that shares no tokens with the target page.

## Rollout / rollback
Fallback path means a missing dep/DB degrades to today's behaviour. Rollback =
revert `__main__` wiring to fakes.

## Status log
- 2026-06-12 — **done**. Embedder: **fastembed `BAAI/bge-small-en-v1.5`, dim 384**
  (`[embed]` extra). New `embed_backends.py`: `LocalEmbedder` (lazy fastembed, stable
  `WIKI_EMBED_CACHE`) + `build_retrieval()` (PgVectorStore + `ensure_schema`; graceful
  fallback to `FakeEmbedder` + new `retrieval.NullVectorStore` when fastembed/DB/env
  missing). `__main__` now `embedder, vectorstore = build_retrieval()` (removed the
  local fakes); `handle_wiki_ingest` accepts `embedder`/`store` and embeds on ingest.
  Tests: `tests/test_embed_backends.py` (4) with a stub embedder — no model/DB needed.
  Full gate green (183 passed, 81.8% cov). Integration paths `# pragma: no cover`.
- **Deploy:** installed `wiki-engine[llm,embed]` into Hermes venv; added
  `WIKI_DB_URL`/`WIKI_EMBED_*`/`WIKI_EMBED_CACHE` to the launcher + `.env`; ran reindex
  (2 rows in `wiki_vectors`). **Verified live:** non-lexical query "which chat
  application are we switching to" retrieved the Slack-migration page via vector recall.
- **Gotcha:** fastembed's default temp cache (`/var/folders/.../T/`) gave a partial
  download → ONNX load error. Fixed by pinning `WIKI_EMBED_CACHE=~/.exale/fastembed_cache`.
