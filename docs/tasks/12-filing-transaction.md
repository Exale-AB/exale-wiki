---
id: T12
title: Give the filing transaction a home (repo.transaction)
phase: 5
priority: P2
status: todo
depends_on: []
effort: M
risk: med
files:
  - packages/wiki-engine/src/wiki_engine/repo.py
  - packages/wiki-engine/src/wiki_engine/ingest.py
  - packages/wiki-engine/src/wiki_engine/query.py
  - packages/wiki-engine/tests/test_repo.py            # extend
  - packages/wiki-engine/tests/test_concurrency.py     # keep green
  - packages/wiki-engine/tests/test_ingest.py          # keep green
  - packages/wiki-engine/tests/test_query.py           # keep green
---

# T12 — One home for "atomically file a page"

> Architecture candidate **#1** ("Strong") from the 2026-06-12 review.

## Problem (verified)

"File a page atomically" — take the write-lock, write the page, upsert its
catalog entry into `index.md`, append a formatted line to `log.md`, then
git-commit — is the wiki's core write transaction. It is open-coded **twice**:

- `ingest.ingest()` — `ingest.py:110–151` (richer: also writes the raw source +
  `manifest.jsonl`, re-checks dedup, and upserts the vector embedding).
- `query._file_answer()` — `query.py:97–118` (the simple case).

Each re-derives the lock acquisition, the
`parse_index → upsert_entry → render_index → write_index` dance, the
`append_log(format_entry(LogEntry(...)))` shape, and the commit message. `WikiRepo`
exposes only low-level primitives (`write_page`, `write_index`, `read_index`,
`append_log`, `commit`, `write_lock`); the **invariant** that index/log/git stay
consistent under the lock lives in the callers' heads.

**Deletion test:** remove the duplicated block and the consistency rules reappear
in every future writer (merge-pages, delete-page, bulk import). It concentrates
complexity → it earns a module.

## Goal / acceptance

- A single deep seam owns: acquire `write_lock` → (caller's writes) → coalesce
  the catalog upsert into one `index.md` write → append one log line → `commit`.
- `ingest()` and `_file_answer()` both express intent through it; neither
  re-implements lock/index/log/commit ordering.
- The seam supports `ingest()`'s **richer in-lock body** (dedup re-check that can
  abort without committing; raw-source + manifest writes; vector upsert).
- Concurrency semantics are **unchanged**: still one cross-process flock,
  model/embedding calls still happen **outside** the lock, the self-deadlock
  footgun (no nested `write_lock`) is preserved and documented.
- No behavioral change to commit messages, log lines, or index output (assert via
  existing `test_ingest` / `test_query` goldens).

## Design

### Shape: a `transaction()` context manager on `WikiRepo`

A `file_page(page, entry, log_entry, message)` one-shot can't host `ingest()`'s
mid-lock dedup re-check + manifest write + conditional abort. A context manager
that **acquires the lock, accumulates index mutations, and commits on clean exit**
fits both callers:

```python
@contextmanager
def transaction(self, message: str, *, timeout: float = 10.0) -> Iterator["WikiTxn"]:
    with self.write_lock(timeout=timeout):
        txn = WikiTxn(self)
        yield txn
        if txn.aborted:
            return                      # skip commit (e.g. dedup race lost)
        if txn._entries is not None:    # coalesce: one index write per txn
            self.write_index(catalog.render_index(txn._entries))
        for line in txn._log_lines:
            self.append_log(line)
        self.commit(message)
```

`WikiTxn` is a tiny mutation recorder bound to the repo:

```python
class WikiTxn:
    def put_page(self, page: Page) -> None      # repo.write_page now
    def catalog(self, entry: CatalogEntry) -> None  # lazily parse_index once, then upsert
    def log(self, entry: LogEntry) -> None       # buffer format_entry(entry)
    def abort(self) -> None                      # exit without commit
    # plus raw-source/manifest/vector helpers OR caller does those directly via repo
```

Key properties:
- **Lock is held for the whole `with` body** — same as today; keep slow model
  calls before `with repo.transaction(...)`.
- **No auto-commit on abort** — the dedup-skip path calls `txn.abort()` then
  `return`s its `IngestResult(skipped=True)`.
- **Index coalescing** — `catalog()` parses `index.md` once on first call and
  upserts in memory; the manager writes it once. (Today each caller does the full
  parse/render itself; behavior identical, just owned by the txn.)
- **Exception safety** — if the body raises, `write_lock`'s `finally` releases the
  flock and we do **not** commit (propagate). Document that a raised exception
  leaves the working tree dirty-but-uncommitted, same as today.

### Rewrite the two callers

`query._file_answer()` collapses to:

```python
def _file_answer(repo, title, text, citations, date) -> str:
    slug = slugify(title)
    with repo.transaction(f"query: {title}") as txn:
        txn.put_page(Page(slug=slug, frontmatter={...}, body=text))
        txn.catalog(CatalogEntry(title=title, slug=slug, category=_FILED_CATEGORY, summary=...))
        txn.log(LogEntry(date=date, op="query", title=title))
    return slug
```

`ingest()`'s in-lock body (`ingest.py:110–151`) moves inside `with
repo.transaction(f"ingest: {source.title}")`, keeping: dedup re-check →
`txn.abort()`+return on hit; raw `.txt` + `_append_manifest`; `txn.put_page`;
schema enforcement (or T11's `schema.enforce_page`); `txn.catalog`; vector
`store.upsert`; `txn.log`. The manager commits on clean exit.

> **Sequence with T11:** if T11 lands first, the enforcement call inside the txn
> becomes `schema.enforce_page(page)`. Independent otherwise — do in either order.

## Test plan (TDD — write these failing first)

In `test_repo.py`:

- `test_transaction_commits_once_on_clean_exit` — uses a spy committer; one
  `commit` call with the given message after the body.
- `test_transaction_does_not_commit_on_abort` — `txn.abort()` → committer never
  called, index/log unchanged.
- `test_transaction_does_not_commit_on_exception` — body raises → committer not
  called, exception propagates, lock released (a second `transaction()` acquires).
- `test_transaction_coalesces_index_writes` — two `catalog()` calls → `index.md`
  written once, both entries present.
- `test_transaction_is_single_locked` — re-entering `write_lock` inside the body
  still self-deadlocks/raises as documented (guard the footgun).

Keep green (behavior-preserving): `test_ingest.py`, `test_query.py`,
`test_concurrency.py` (the parallel-ingest race from T07 must still be fixed —
this is the highest-value regression guard).

## Verification

```bash
uv run pytest packages/wiki-engine/tests/test_repo.py packages/wiki-engine/tests/test_concurrency.py -v
uv run pytest
uv run ruff check . && uv run ruff format --check . && uv run pyright
```

Engine-internal; no MCP schema change. Still redeploy + `hermes mcp test
wiki-engine` because it rewrites the live write path, and manually run a
**parallel ingest** through the launcher to re-confirm no lost index entries.

## Rollback

Revert `repo.py` + the two callers. The `transaction`/`WikiTxn` additions are
self-contained; callers are the only behavioral change.

## Notes

- Honors the architecture invariant *"every operation ends in `repo.commit(...)`
  (injectable committer)"* — the committer stays injected; the txn just owns the
  choreography around it.
- Do **not** widen the lock scope to include model/embedding calls — that would
  regress latency under concurrency (the whole point of T07 keeping them outside).
- `_git_commit` stays `# pragma: no cover`; tests inject a spy committer as today.

## Status log
- _(todo)_
