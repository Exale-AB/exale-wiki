---
id: T03
title: Add wiki_context tool (raw ranked context, no LLM)
phase: 1
priority: P1
status: done
depends_on: []
effort: M
risk: low
files:
  - packages/wiki-engine/src/wiki_engine/mcp_server.py
  - packages/wiki-engine/src/wiki_engine/__main__.py
  - packages/wiki-engine/tests/test_mcp_context.py  # new
---

# T03 — `wiki_context`: fast raw context, no synthesis

## Problem
`wiki_query` always **synthesizes** an answer (the `HermesAnswerer` LLM call). When
the caller is itself a Hermes workflow, that means: extra latency + a model round
trip + **double-synthesis** (engine writes prose, agent then reasons over prose
instead of source material). The north-star use case — *"give my workflow context
to ground its own reasoning"* — wants **ranked raw context**, fast, no LLM.

## Goal / acceptance
- New MCP tool `wiki_context(query, k=5, token_budget=2000)` returns:
  `{ "context": [ {slug, title, text, score?} ... ], "citations": [slug, ...] }`
  with **no model call**.
- Total returned text respects `token_budget` (approx; char/4 heuristic until T08).
- Empty/no-hit query → empty `context` + `citations`.

## Design
- Reuse `Retriever.retrieve(query, k)` for slugs → `repo.read_page(slug)` for bodies.
  No `Answerer`. Truncate the concatenated bodies to `token_budget * 4` chars,
  preferring whole pages, recording which slugs made it in as `citations`.
- Add `handle_wiki_context(repo, query, k, token_budget, vectorstore, embedder)` in
  `mcp_server.py`; add its schema to `wiki_mcp_tools()`; wire into
  `__main__.handle_request` (`elif tool_name == "wiki_context"`).
- This shares the retriever with `wiki_query`, so it automatically benefits from
  T05 semantic retrieval once that lands.

## Test plan (TDD)
`tests/test_mcp_context.py`:
- `test_context_returns_raw_pages_and_citations` — seed pages; assert the bodies
  come back verbatim and citations match retrieved slugs; assert **no Answerer is
  invoked** (inject a spy answerer that fails if called — or simply don't pass one).
- `test_context_respects_token_budget` — small budget truncates page set.
- `test_context_empty_query_returns_empty`.

## Verification
```bash
uv run pytest packages/wiki-engine/tests/test_mcp_context.py -v
uv run pytest
```
Redeploy; via launcher call `wiki_context` and confirm raw snippets + citations,
fast (no model latency).

## Notes
Token-budget quality improves with T08 (chunking). Ship the naive whole-page +
truncate version first; T08 swaps in chunk-level ranking.

## Status log
- 2026-06-12 — **done**. Added `wiki_context` tool: `handle_wiki_context(repo, query,
  *, vectorstore, embedder, k=5, token_budget=2000)` reuses the `Retriever`, packs
  page bodies under a char/4 token budget (always returns ≥1 top hit), returns
  `{context:[{slug,title,text}], citations:[...]}` — **no `Answerer`/LLM call**.
  Schema added to `wiki_mcp_tools()`; wired into `__main__.handle_request`. Tests:
  `tests/test_mcp_context.py` (3); updated `test_render.py` tool-count 3→4. Full gate
  green (174 passed, 81.5% cov). Redeployed; `hermes mcp test` shows 4 tools; verified
  raw snippets + citations via launcher.
- Naive whole-page truncation for now; **T08** swaps in chunk-level budgeting.
