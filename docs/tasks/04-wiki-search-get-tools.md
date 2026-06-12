---
id: T04
title: Add wiki_search and wiki_get tools
phase: 1
priority: P2
status: done
depends_on: []
effort: M
risk: low
files:
  - packages/wiki-engine/src/wiki_engine/mcp_server.py
  - packages/wiki-engine/src/wiki_engine/__main__.py
  - packages/wiki-engine/tests/test_mcp_search_get.py  # new
---

# T04 — `wiki_search` + `wiki_get`

## Problem
The MCP exposes only `query`/`ingest`/`lint`. A workflow cannot cheaply:
- **check existence** before ingesting (→ duplicate pages), or
- **fetch a known page** by slug.

The skill's "orient first" pattern (search the index, read a page) is impossible as
tools — `wiki_query` is the only read path and it synthesizes.

## Goal / acceptance
- `wiki_search(query, k=10)` → `[{slug, title, summary, score}]` — ranked hits, **no
  synthesis, no full bodies** (cheap existence/browse).
- `wiki_get(slug)` → `{slug, title, frontmatter, body}` or `{found: false}`.

## Design
- `wiki_search`: rank via the structural path (`catalog.parse_index` token overlap)
  + vector hits when available; return catalog metadata (title/summary) only.
  Lighter than `wiki_context` (no bodies).
- `wiki_get`: `repo.read_page(slug)` → serialize frontmatter + body; `None` →
  `{found: false}`.
- Add tool schemas to `wiki_mcp_tools()`; handlers in `mcp_server.py`; wire both into
  `__main__.handle_request`.

## Test plan (TDD)
`tests/test_mcp_search_get.py`:
- `test_search_ranks_matches_without_bodies` — seeded index; assert ordering and
  that bodies are absent from the result.
- `test_get_returns_page` / `test_get_unknown_slug_returns_not_found`.

## Verification
```bash
uv run pytest packages/wiki-engine/tests/test_mcp_search_get.py -v
uv run pytest
```

## Notes
`wiki_search` pairs with T01: an agent can `wiki_search` first, and only `wiki_ingest`
when nothing matches — defense in depth against duplicates.

## Status log
- 2026-06-12 — **done**. Added `wiki_search(query, k=10)` → `{results:[{slug, title,
  summary, category, score}]}` (catalog metadata via `catalog.parse_index`, token-
  overlap score, **no bodies**) and `wiki_get(slug)` → full page or `{found: false}`.
  Schemas + `__main__` wiring added; tool count 4→6. Tests:
  `tests/test_mcp_search_get.py` (3). Full gate green (177 passed, 81.0% cov).
  Redeployed; `hermes mcp test` shows 6 tools; verified search/get via launcher.
