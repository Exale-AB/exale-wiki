---
id: T07
title: Concurrency — per-repo write lock for mutating operations
phase: 3
priority: P1
status: done
depends_on: []
effort: M
risk: med
files:
  - packages/wiki-engine/src/wiki_engine/repo.py
  - packages/wiki-engine/src/wiki_engine/ingest.py
  - packages/wiki-engine/src/wiki_engine/query.py   # file-as-new-page path
  - packages/wiki-engine/tests/test_concurrency.py  # new
---

# T07 — Per-repo write lock

## Problem (verified — no locking anywhere)
Every mutating op does a full `git add -A && git commit` on the wiki dir plus a
**read-modify-write of `index.md` and `log.md`** (`catalog.parse_index` → `render_index`
→ `write_index`; `append_log`). With multiple Hermes workflows ingesting
concurrently this races:
- `git index.lock` contention → failed/partial commits;
- **lost index/log updates** (two readers, two writers, last-writer-wins);
- interleaved manifest/page writes.

There is no lock in `packages/wiki-engine/src/`. This is the top reliability risk
once "all processes" write to one shared repo.

## Goal / acceptance
- Concurrent mutating operations on the same repo are **serialized**; final state is
  consistent (every page present, `index.md` contains every entry, log has every
  line, git history is linear and clean).
- Read-only ops (`query` without filing, `wiki_context`, `wiki_search`, `wiki_get`)
  are **not** blocked unnecessarily.
- Lock acquisition has a timeout with a clear error; never deadlocks.

## Design
- Add a process-safe lock around the mutate+commit section. Prefer **stdlib
  `fcntl.flock`** on `<repo>/.wiki.lock` (deploy is macOS/Linux — no new dep), exposed
  as a `WikiRepo` context manager:
  ```python
  with repo.write_lock(timeout=10):
      ... ingest mutate + commit ...
  ```
  (If Windows support is ever needed, swap to the small `filelock` dep behind the
  same interface — record the decision.)
- Wrap the mutating bodies of `ingest()`, `query()`'s file-as-new-page branch, and
  the lint log-append. Keep the critical section tight (do the LLM summarize call
  **outside** the lock — only the filesystem/git writes need it).

## Test plan (TDD)
`tests/test_concurrency.py`:
- `test_parallel_ingests_all_pages_and_index_entries` — N threads ingest distinct
  sources into one repo (real git committer in a tmp dir); assert all N pages exist,
  `parse_index` has N entries, `git log` has N commits, no `.lock` left behind.
- `test_write_lock_times_out_cleanly` — hold the lock, assert a second acquire raises
  a timeout error rather than hanging.

## Verification
```bash
uv run pytest packages/wiki-engine/tests/test_concurrency.py -v
uv run pytest
```

## Notes
This also makes T01's dedup race-safe (manifest read+write inside the lock). Keep the
summarize/embed model calls out of the critical section to avoid holding the lock for
seconds.

## Status log
- 2026-06-12 — **done**. Added `WikiRepo.write_lock(timeout=10.0)` — a `fcntl.flock`
  advisory lock on `<repo>/.wiki.lock`, raising `TimeoutError` on contention.
  `ingest()` and `query._file_answer()` now wrap their dedup + filesystem/git writes
  in it; **model calls (summarize/embed) are kept outside the lock**, with an
  optimistic dedup pre-check before summarize + an authoritative re-check inside.
  `WikiRepo.init` writes a `.gitignore` for the lock file (also added to the live
  seat). Tests: `tests/test_concurrency.py` (2) — the parallel test was a definitive
  RED (lost 5/8 index entries without the lock) and is green + non-flaky (3× runs)
  with it. Full gate green (185 passed, 82.0% cov, ruff/pyright clean). Redeployed;
  ingest verified through the launcher; `.wiki.lock` confirmed untracked by git.
- POSIX `flock` only (macOS/Linux deploy). For Windows, swap to the `filelock` dep
  behind the same `write_lock` interface.
