---
id: T11
title: Make WikiSchema enforce itself (one ruleset, one off-limits key)
phase: 5
priority: P1
status: todo
depends_on: []
effort: M
risk: med
files:
  - packages/wiki-engine/src/wiki_engine/schema.py
  - packages/wiki-engine/src/wiki_engine/ingest.py
  - packages/wiki-engine/tests/test_schema_enforcement.py   # extend
  - packages/wiki-engine/tests/test_schema.py               # extend
  - packages/wiki-engine/tests/test_ingest.py               # extend
  - CLAUDE.md                                               # note canonical off-limits key
---

# T11 — The rulebook enforces itself

> Architecture candidate **#2** ("Strong" / top recommendation) from the
> 2026-06-12 architecture review. This is the cleanup foreshadowed in
> [T02](02-enforce-seat-schema.md)'s *Gotcha discovered*.

## Problem (verified)

`WikiSchema` is the per-seat rulebook, but enforcement is a **bag of five free
functions** that a caller must remember to invoke, in the right order, against
the right inputs:

| function | reads | called by `ingest()`? |
|---|---|---|
| `enforce_source_kind(kind, schema)` | `allowed_source_kinds` | ✅ `ingest.py:90` |
| `validate_ingestion_category(cat, honesty_rules)` | `honesty_rules["off_limits"]` | ✅ `ingest.py:129` |
| `enforce_honesty_category(page, schema)` | `honesty_rules["off_limits_categories"]` | ✅ `ingest.py:131` |
| `enforce_page_type_frontmatter(page, schema)` | `page_type_rules[*].required_*` | ❌ **never** |
| `enforce_page_category(page, schema)` | `page_type_rules[*].allowed_categories` | ❌ **never** |

Two concrete defects fall straight out of this scattering:

1. **Off-limits key mismatch (live bug).** The early ingest guard
   (`ingest.py:92`, via `off_limits` passed from `mcp_server.py:414`) and
   `enforce_honesty_category` both read `honesty_rules.off_limits_categories`.
   But `validate_ingestion_category` reads a top-level/`honesty_rules` key named
   `off_limits` — which nothing else writes. For a correctly-configured seat
   (canonical `off_limits_categories`), the `ingest.py:129` call is a **silent
   no-op**. Confirmed: `grep -n off_limits schema.py ingest.py mcp_server.py`.
2. **Page-type rules unenforced on ingest.** `ingest()` never calls
   `enforce_page_type_frontmatter` / `enforce_page_category`, so a seat's
   `page_type_rules` (required frontmatter, allowed categories) are decorative
   in the ingest path.

The interface is "know these 5 functions and their correct call order" — nearly
as complex as the implementation. The real risk is the *composition*, which no
single test exercises.

## Goal / acceptance

- A **single** deep entry point on the schema validates a page (and, on ingest,
  the source) by running the **whole** ruleset in one defined order.
- Exactly **one** off-limits concept, one key: `honesty_rules.off_limits_categories`.
  The stray `off_limits` key path is removed (or made an explicit alias with a
  deprecation note) so the two can never disagree again.
- `ingest()` calls that one method — it can no longer enforce a partial subset.
- Page-type frontmatter + category rules **are** enforced on ingest.
- No behavioral regression for the off-limits exclusion already shipped in T02
  (off-limits category still returns `excluded` *before* any page/LLM work).
- Public API surface change is intentional and reflected in `test_public_api.py`.

## Design

### 1. One enforcement method on `WikiSchema`

Add a single ordered entry point. Keep validation cheap and pure (raises
`SchemaError`, returns `None`):

```python
class WikiSchema:
    ...
    @property
    def off_limits_categories(self) -> tuple[str, ...]:
        """Canonical off-limits list. The ONLY place this key is read."""
        raw = self.honesty_rules.get("off_limits_categories", [])
        return tuple(raw)

    def enforce_source(self, source: Source) -> None:
        """Pre-summarize gate: source kind + off-limits category."""
        _enforce_source_kind(str(source.kind), self)
        if set(source.categories) & set(self.off_limits_categories):
            raise OffLimitsError(...)          # or keep the early-return contract

    def enforce_page(self, page: Page) -> None:
        """Pre-persist gate: page-type frontmatter, category, honesty."""
        _enforce_page_type_frontmatter(page, self)
        _enforce_page_category(page, self)
        _enforce_honesty_category(page, self)   # uses off_limits_categories
```

> **Decision to settle in design (see Notes):** off-limits as **early return**
> (current ingest contract → `IngestResult(excluded=True)`) vs **raised
> exception**. The early guard in ingest currently returns `excluded`, not
> raises, so keep `enforce_source` returning a result or keep the membership
> check in `ingest` and have `enforce_source` cover only `enforce_source_kind`.
> Do not change the excluded-vs-raised contract without updating T02's tests.

### 2. Collapse the off-limits duplication

- Delete `validate_ingestion_category` + `get_off_limits_categories` (the
  `off_limits` top-level key path), OR keep them as thin shims that read the
  canonical key and emit a `DeprecationWarning`. Prefer deletion — `grep`
  confirms the only caller is `ingest.py:129`, which this task rewrites.
- Update `__all__` in `schema.py` accordingly.

### 3. Keep the five free functions as private helpers

Rename to `_enforce_*` (module-private) and route the public methods through
them, **or** keep the public names as backward-compatible wrappers delegating to
the methods. Choose based on whether `test_schema_enforcement.py` /
`test_schema.py` should keep testing them directly (they currently do). Lowest-
churn path: keep the public function names, have them delegate to the methods,
and add the new methods as the preferred surface.

### 4. Rewrite the `ingest()` enforcement block

Replace the hand-picked trio (`ingest.py:90`, `128–131`) with:

```python
schema.enforce_source(source)              # before dedup / summarize
...
page = Page(...)
schema.enforce_page(page)                  # before repo.write_page(page)
```

Order matters: source kind + off-limits stay **before** the costly summarize;
page-type/category/honesty stay **before** persisting the page.

## Test plan (TDD — write these failing first)

In `test_schema_enforcement.py` / `test_ingest.py`:

- `test_ingest_enforces_page_type_required_frontmatter` — schema with a
  `page_type_rule` requiring a field the ingested page lacks → `SchemaError`
  (currently **passes through**; this is the gap-closing red test).
- `test_ingest_enforces_page_type_allowed_categories` — page-type restricts
  categories; ingest into a disallowed one → `SchemaError`.
- `test_off_limits_single_key` — a schema with `off_limits_categories: [legal]`
  excludes `legal`; a schema with the *legacy* `off_limits: [legal]` key does
  **not** silently exclude (documents the canonical key). Lock the behavior so
  the dual-key ambiguity can't return.
- `test_schema_enforce_page_runs_full_ruleset` — one call raises on the first
  violated rule across type/category/honesty (composition test).
- `test_off_limits_excluded_still_pre_summarize` — regression: off-limits source
  returns `excluded` without invoking the summarizer (assert a spy summarizer is
  never called). Protects T02 + T10 contracts.

Update `test_public_api.py` for the changed `schema` exports.

## Verification

```bash
uv run pytest packages/wiki-engine/tests/ -k "schema or off_limits or ingest" -v
uv run pytest                       # ≥80% cov
uv run ruff check . && uv run ruff format --check . && uv run pyright
```

Engine-only change (no MCP wire change), so **no redeploy strictly required** —
but `handle_wiki_ingest` builds `off_limits` from
`honesty_rules.off_limits_categories` already, so confirm the launcher still
excludes `personal-finances` after the refactor.

## Rollback

Pure engine refactor; revert `schema.py` + `ingest.py`. The new methods are
additive; the risk is the deletion of the `off_limits` path — keep it a shim in
the first commit if you want a smaller blast radius, delete in a follow-up.

## Notes

- Settle the **early-return vs raise** contract for off-limits before coding; it
  determines whether `enforce_source` returns or raises (see Design §1).
- This names a concept — "the seat's enforced ruleset" — that has no entry in a
  domain glossary because the repo has no `CONTEXT.md`. Consider creating one
  lazily and recording: *off-limits categories live under
  `honesty_rules.off_limits_categories`; there is no other key.*
- Out of scope (tracked elsewhere): generating `schema/AGENTS.md` from
  `seat.yaml` so the rulebook and the seat config can't drift (noted in T02).

## Status log
- _(todo)_
