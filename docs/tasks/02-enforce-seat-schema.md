---
id: T02
title: Load & enforce the seat schema/AGENTS.md in the MCP path
phase: 1
priority: P1
status: done
depends_on: []
effort: M
risk: med
files:
  - packages/wiki-engine/src/wiki_engine/mcp_server.py
  - packages/wiki-engine/src/wiki_engine/repo.py
  - packages/wiki-engine/src/wiki_engine/schema.py        # confirm parse_schema signature
  - packages/wiki-engine/tests/test_schema_enforcement.py # extend
---

# T02 — Enforce the seat rulebook in the live path

## Problem (verified)
Both MCP handlers build a **default** schema and ignore the seat rulebook:

```python
# handle_wiki_ingest
schema = WikiSchema(default_category=category)
# handle_wiki_lint
schema = WikiSchema()
```

So the seat's `schema/AGENTS.md` — `off_limits` (`personal-finances`,
`legal-disputes`, `health-records`), `allowed_source_kinds`, honesty rules, and
`lint_thresholds` — is **not enforced at runtime**. The rulebook is decorative in
the deployed path. For a shared, governed context store this is a real gap.

The engine already has the pieces: `schema.parse_schema(...)`,
`schema.get_off_limits_categories(...)`, `ingest(..., off_limits=...)`, and
`WikiRepo.schema_dir`. They are just never wired into the handlers.

## Goal / acceptance
- MCP `wiki_ingest` **rejects** a source whose category is in the schema's
  `off_limits` (returns an "excluded" result, no page written).
- MCP `wiki_ingest` enforces `allowed_source_kinds` / honesty rules per the schema.
- MCP `wiki_lint` uses the schema's `lint_thresholds`.
- Missing/malformed `schema/AGENTS.md` → fall back to a sane default schema and log
  to stderr (never crash).

## Design
1. Add `WikiRepo.schema_path` → `schema_dir / "AGENTS.md"` and a small loader
   `load_seat_schema(repo) -> WikiSchema` (new helper in `schema.py` or `repo.py`):
   read the file, `parse_schema(text)`; on missing/parse error, return
   `WikiSchema(default_category=...)` and `_warn(...)`.
   *(Confirm `parse_schema` input — text vs path — before coding.)*
2. In `handle_wiki_ingest`: load the seat schema once; pass it **and**
   `off_limits=get_off_limits_categories(schema)` into `ingest(...)`. Map an
   `IngestResult(excluded=True)` to a clear MCP response (e.g.
   `{"slug": "", "excluded": true, "reason": "off_limits:<category>"}`).
3. In `handle_wiki_lint`: load the seat schema and pass it to `lint(...)`.

## Test plan (TDD)
Extend `test_schema_enforcement.py` (and/or new `test_mcp_schema.py`):
- `test_mcp_ingest_rejects_off_limits_category` — schema with `off_limits:
  [health-records]`; ingest category `health-records` → excluded, no page.
- `test_mcp_ingest_allows_permitted_category`.
- `test_mcp_lint_uses_schema_thresholds` — duplicate-similarity threshold from
  schema changes which violations surface.
- `test_load_seat_schema_falls_back_when_absent`.

Use the existing fixture `seeded_defects_wiki/schema/AGENTS.md` as a realistic schema.

## Verification
```bash
uv run pytest packages/wiki-engine/tests/ -k "schema or off_limits" -v
uv run pytest
```
Manual: with `myagent/wiki/schema/AGENTS.md` listing off-limits, ingest an
off-limits category through the launcher → rejected.

## Rollback
Revert handler changes; loader helper is additive.

## Notes
The seat's `seat.yaml` already declares `off_limits`. A future task could *generate*
`schema/AGENTS.md` from `seat.yaml` so the two can't drift — out of scope here.

## Status log
- 2026-06-12 — **done**. Added `mcp_server.load_seat_schema(repo)` (parses
  `schema/AGENTS.md`, falls back to default + stderr warn). `handle_wiki_ingest`
  now loads the seat schema, overrides `default_category` with the per-ingest
  category (preserves page metadata), and passes
  `off_limits = honesty_rules.off_limits_categories` to `ingest()` → off-limits
  categories return `status: excluded` *before* any page/LLM work. `handle_wiki_lint`
  loads the seat schema too. Tests: `tests/test_mcp_schema.py` (4, green).
  Full gate green (171 passed, 81.5% cov, ruff/pyright clean).
- **Seat fix:** the generated `schema/AGENTS.md` used an unwired top-level
  `off_limits:` key; corrected to the canonical `honesty_rules.off_limits_categories`
  in `setup.sh` **and** the live seat file. Redeployed; verified via launcher:
  `personal-finances` → excluded, `ops` → created.

## Gotcha discovered
The engine has two off-limits keys: `honesty_rules.off_limits_categories` (canonical,
used by `enforce_honesty_category` and all tests/fixtures) and a stray top-level
`off_limits` (only read by `get_off_limits_categories`/`validate_ingestion_category`).
Standardize on `honesty_rules.off_limits_categories`. A future cleanup could collapse
these and also generate `AGENTS.md` from `seat.yaml` so they can't drift.
