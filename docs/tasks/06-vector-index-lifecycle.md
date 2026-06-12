---
id: T06
title: Vector index lifecycle (rebuild / backfill from markdown)
phase: 2
priority: P2
status: done
depends_on: []
effort: M
risk: med
files:
  - packages/wiki-engine/src/wiki_engine/reindex.py  # new
  - packages/wiki-engine/src/wiki_engine/retrieval.py
  - packages/wiki-engine/tests/test_reindex.py       # new
---

# T06 — Vector index lifecycle

## Problem
The vector index is a **derived** artifact (markdown is the system of record), but
there is no way to (re)build it. Once T05 wires embed-on-ingest, any pages created
before the embedder existed — or edited directly on disk, or restored from git —
will be **missing from / stale in** the vector store. Without a rebuild path the
index silently drifts and semantic recall rots.

## Goal / acceptance
- `python -m wiki_engine.reindex` (reads `WIKI_REPO_PATH`, `WIKI_DB_URL`/`DATABASE_URL`,
  `WIKI_EMBED_*`) rebuilds `wiki_vectors` from all current pages:
  `ensure_schema()` → for each `repo.list_pages()`: embed body → `store.upsert(slug,
  vec)`.
- Idempotent (re-running yields the same state; uses upsert).
- Reports counts (pages embedded, skipped).
- Optional `--prune` removes vectors whose slug no longer has a page.

## Design
- `reindex.py`: `reindex(repo, embedder, store, *, prune=False) -> ReindexResult`
  plus a `main()` that builds embedder/store via `embed_backends.build_retrieval()`
  (T05) and runs it. Add to `[project.scripts]` or run as `-m`.
- `PgVectorStore`: add a `slugs()` / `delete(slug)` helper if `--prune` is in scope.

## Test plan (TDD)
`tests/test_reindex.py` (use `InMemoryVectorStore` + stub embedder):
- `test_reindex_populates_store_from_pages`.
- `test_reindex_is_idempotent`.
- `test_reindex_prune_removes_orphan_vectors` (if implemented).

## Verification
```bash
uv run pytest packages/wiki-engine/tests/test_reindex.py -v
uv run pytest
```
Integration: against native PG, ingest a few pages, drop the table, run reindex,
confirm `SELECT count(*) FROM wiki_vectors` matches page count.

## Deployment hook
Document running `reindex` after bulk markdown edits / git restores. Optionally have
the seat `setup.sh` run it once at provision time (guard: only if `[embed]` installed
and DB reachable).

## Status log
- 2026-06-12 — **done**. `reindex.py`: `reindex(repo, embedder, store) -> ReindexResult`
  (embeds every `repo.list_pages()` body, upserts; idempotent) + `python -m
  wiki_engine.reindex` `main()` (builds embedder/store via `build_retrieval()`).
  Tests: `tests/test_reindex.py` (2) with stub embedder + `InMemoryVectorStore`.
  Verified live: reindex backfilled the seat's 2 pages → 2 rows in `wiki_vectors`.
- **Scope cut:** `--prune` deferred — needs `slugs()`/`delete()` on `PgVectorStore`
  (not present). Tracked as a future addition; left out to keep this clean.
