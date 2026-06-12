---
id: T08
title: Token-budgeted chunked retrieval
phase: 4
priority: P3
status: done
depends_on: [T03]
effort: M
risk: med
files:
  - packages/wiki-engine/src/wiki_engine/chunk.py        # new
  - packages/wiki-engine/src/wiki_engine/retrieval.py
  - packages/wiki-engine/src/wiki_engine/mcp_server.py   # wiki_context / wiki_query
  - packages/wiki-engine/tests/test_chunk.py             # new
---

# T08 — Chunking + token budget

## Problem
Retrieval returns **whole page bodies**. A few large pages can blow the caller's
context window, and ranking is page-granular (a 200-line page matches on one
paragraph but the whole thing is returned). For a shared context layer feeding many
prompts, retrieval should return **the most relevant chunks** under an explicit
token budget.

## Goal / acceptance
- A chunker splits page bodies into coherent chunks (by markdown heading / paragraph,
  target ~N tokens, with small overlap).
- `wiki_context` (T03) and `wiki_query` rank and return **chunks** (each tagged with
  its parent slug) packed to `token_budget`.
- Citations still resolve to parent pages.

## Design
- `chunk.py`: `chunk_page(page, *, max_tokens, overlap) -> list[Chunk]` where
  `Chunk = {slug, heading, text, char_span}`. Split on headings first, then by
  paragraph to stay under budget. Token estimate via char/4 heuristic (no dep); if a
  precise count is ever needed, add `tiktoken` behind an extra.
- Retrieval: after selecting candidate pages, chunk them, score chunks against the
  query (reuse the structural token overlap and/or embeddings from T05), and pack the
  top chunks until `token_budget` is reached.
- `wiki_context` returns `[{slug, heading, text, score}]`; the budget is honored at
  chunk granularity (much better than whole-page truncation).

## Test plan (TDD)
`tests/test_chunk.py`:
- `test_chunk_splits_on_headings_and_respects_max_tokens`.
- `test_chunk_overlap_preserves_boundary_context`.
- `test_context_packs_top_chunks_within_budget` (retrieval-level) — assert the
  returned chunk set is under budget and ordered by score, citations map to parents.

## Verification
```bash
uv run pytest packages/wiki-engine/tests/test_chunk.py -v
uv run pytest
```

## Notes
Supersedes the naive whole-page truncation shipped in T03. Keep `wiki_get` returning
**full** pages (chunking is a retrieval concern, not a fetch concern).

## Status log
- 2026-06-12 — **done**. New `chunk.py`: `chunk_page(slug, body, *, max_tokens=256)`
  → `[Chunk(slug, heading, text)]` — splits on markdown headings, packs paragraphs
  under a char/4 budget, hard-splits oversized paragraphs. `wiki_context` now packs
  **chunks** (not whole pages) under `token_budget`, returning
  `{slug, title, heading, text, score}` with de-duplicated citations. Tests:
  `tests/test_chunk.py` (4); T03 context tests stay green (short pages → one chunk =
  full body, backward-compatible). Full gate green (189 passed, 82.6% cov). Redeployed;
  verified chunk-level fields via launcher.
- `wiki_get` still returns full pages (chunking is a retrieval concern only).
