---
id: T01
title: Fix MCP ingest dedup (content-hash identifier)
phase: 1
priority: P1
status: done
depends_on: []
effort: S
risk: low
files:
  - packages/wiki-engine/src/wiki_engine/mcp_server.py
  - packages/wiki-engine/tests/test_mcp_ingest.py  # new
---

# T01 — Fix MCP ingest dedup

## Problem (verified)
`handle_wiki_ingest` builds the source identity from a **memory address**:

```python
# mcp_server.py (text branch)
identifier=f"mcp-text-{id(source_text)}",
```

`Source.identity()` is `sha256(kind + identifier + text)`. Because `id()` returns a
new address each call, ingesting the **same text twice produces different
identities**, so the manifest dedup in `ingest.py` (`if source.identity() in
_manifest_ids(repo): return skipped`) never fires. Result: **duplicate pages** on
every re-ingest of identical content. With many workflows ingesting into a shared
wiki, this pollutes the store quickly.

## Goal / acceptance
- Ingesting the **same `source_text` + `category` twice** → the second call returns
  `skipped=True` and creates **no** new page/manifest entry.
- Different text still produces distinct pages.
- URL ingests already use `identifier=source_url` (stable) — leave unchanged.

## Design
Derive a **stable** identifier from the content:

```python
import hashlib
identifier = "text:" + hashlib.sha256(source_text.encode("utf-8")).hexdigest()[:16]
```

Identity stays content-addressed (same text → same identity → dedup hits). Title
remains the first line.

## Changes
- `mcp_server.handle_wiki_ingest`: replace the `id(source_text)` identifier with the
  content hash above (text branch only).

## Test plan (TDD — write first, watch fail)
`tests/test_mcp_ingest.py`:
- `test_ingest_same_text_twice_is_skipped` — call `handle_wiki_ingest` twice with
  identical text/category against a temp `WikiRepo`; assert first creates a page,
  second reports skipped and `repo.list_pages()` count is unchanged.
- `test_ingest_different_text_creates_distinct_pages`.

Use a `WikiRepo.init(tmp_path, committer=lambda *_: None)` and `FakeSummarizer` (no
model). Assert on the returned dict (`slug`) and `repo` state.

## Verification
```bash
uv run pytest packages/wiki-engine/tests/test_mcp_ingest.py -v
uv run pytest   # full gate
```
Redeploy + manual: ingest identical text twice through the launcher; confirm one page.

## Rollback
Single-line revert.

## Status log
- 2026-06-12 — **done**. Identifier is now `text:<sha256[:16]>` (content-addressed);
  added a `status` field (`created|updated|skipped|excluded`) to the ingest response.
  Tests: `tests/test_mcp_ingest.py` (3, green). Full gate green (167 passed, 81.2%
  cov, ruff/pyright clean). Redeployed to Hermes venv; verified via launcher:
  identical text → `created` then `skipped`.

## Follow-up surfaced
- The response now exposes `status` — T10 (provenance) and the `wiki_search`-before-
  `wiki_ingest` pattern (T04) build on this.
