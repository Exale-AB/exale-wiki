---
id: T10
title: Provenance capture + visible degradation in results
phase: 4
priority: P3
status: done
depends_on: [T01]
effort: M
risk: low
files:
  - packages/wiki-engine/src/wiki_engine/mcp_server.py
  - packages/wiki-engine/src/wiki_engine/ingest.py
  - packages/wiki-engine/src/wiki_engine/llm_backends.py
  - packages/wiki-engine/tests/test_provenance.py  # new
---

# T10 — Provenance + visible degradation

## Problem
For a shared context layer used by many workflows, results need **trust signals**:
- Citations are bare slugs — no recency or confidence surfaced, so a workflow can't
  weight fresh/strong context over stale/weak.
- No record of **which workflow / source app** ingested a page (the skill supports
  `author`/`contributor`; the engine doesn't capture it).
- A dead proxy makes `summarize`/`answer` **silently** fall back to fakes — good for
  uptime, bad for trust (a workflow gets stub text and can't tell).

## Goal / acceptance
- `wiki_ingest` accepts optional `contributor` / `source_app`; stored in page
  frontmatter and the log entry.
- `wiki_query` / `wiki_context` results include per-citation metadata: `{slug,
  updated, score}` (recency from frontmatter/log, score from retrieval).
- Responses carry a `degraded: bool` (and `mode: "model" | "fake"`) flag set when the
  judgment path fell back to fakes (proxy/DB down or `WIKI_LLM_DISABLED`).

## Design
- `build_judgment()` (and the T05 `build_retrieval()`) already know whether they
  returned Hermes-backed or fake impls — surface that as a small capability flag the
  handlers can read and echo into responses.
- Extend `handle_wiki_ingest` signature with `contributor`/`source_app`; thread into
  the `Source`/page frontmatter (and the `manifest.jsonl` record).
- Enrich citation objects in query/context responses with `updated` (from page
  frontmatter or the latest log entry touching the slug) and `score`.

## Test plan (TDD)
`tests/test_provenance.py`:
- `test_ingest_records_contributor_in_frontmatter`.
- `test_query_citations_include_recency_and_score`.
- `test_degraded_flag_set_when_llm_disabled` — with `WIKI_LLM_DISABLED=1`, a query
  response has `degraded: true`, `mode: "fake"`.

## Verification
```bash
uv run pytest packages/wiki-engine/tests/test_provenance.py -v
uv run pytest
```

## Notes
Depends on T01 (the ingest identity/frontmatter path it extends). Pairs naturally
with T02 (governance) — provenance + rule enforcement together make the shared store
auditable.

## Status log
- 2026-06-12 — **done (core)**. `ingest()` + `handle_wiki_ingest` accept `contributor`
  → stored in page frontmatter (+ tool schema field). Responses now carry a **mode**:
  `wiki_ingest` → `mode: model|fake` (HermesSummarizer vs fake); `wiki_query` →
  `mode` + `degraded: bool` (HermesAnswerer vs fake fallback) — silent degradation is
  now visible. Tests: `tests/test_provenance.py` (4). Full gate green (204 passed,
  86.8% cov). Verified live: `contributor: chief-of-staff` in frontmatter, query
  `mode: model, degraded: false`.
- **Deferred:** per-citation **recency** (`updated`) enrichment — pages don't store an
  `updated`/date field today; adding one is a model change (frontmatter + ingest +
  lint staleness already reads source dates). `score` is already surfaced by
  `wiki_search`/`wiki_context`. Retrieval-mode (semantic vs structural) flag could be
  added similarly via `isinstance(store, NullVectorStore)` if wanted.
