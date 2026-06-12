# Wiki Engine Roadmap — Shared Context Layer for Hermes Workflows

> **North star:** make the Self-Improving Knowledge Wiki the reliable, low-latency
> **context layer that every Hermes workflow reads from** to ground any AI task.
> Today it is a single-writer, structural-only, synthesize-on-read store; this
> roadmap turns it into a concurrent, semantically-retrievable, governed context
> service.

This file is the **source of truth for tracking**. Each task has a detailed spec
under [`docs/tasks/`](tasks/). A task spec is self-contained — a future Claude Code
session should be able to pick one up cold.

---

## How to use this roadmap (for a future Claude Code session)

1. Read this file. Pick the **lowest-numbered `todo` task whose `depends_on` are all
   `done`** (numbering is the recommended order).
2. Open its spec in `docs/tasks/NN-*.md`. Follow the **TDD plan** (write the listed
   failing tests first, then implement).
3. Run the **Verification** block in the spec. The repo-wide gate must stay green:
   `uv run pytest` (≥80% coverage), `uv run ruff check .`, `uv run ruff format --check .`,
   `uv run pyright`.
4. If the change touches the MCP/runtime path, **redeploy**: reinstall into the
   Hermes venv (`~/.hermes/hermes-agent/venv/bin/python3 -m pip install -e
   packages/wiki-engine[llm]`), re-run the seat `setup.sh`, and confirm
   `hermes mcp test wiki-engine`. See `CLAUDE.md` and the deployment memory.
5. Flip the task's `status:` frontmatter to `done`, check its box in the table
   below, and append a dated line to the **Changelog**.

**Status values:** `todo` · `in-progress` · `blocked` · `done`
**Effort:** S (≤½ day) · M (1–2 days) · L (3+ days) · **Risk:** low/med/high

---

## Status table

| # | Task | Phase | Pri | Effort | Risk | Depends on | Status |
|---|------|-------|-----|--------|------|------------|--------|
| 01 | [Fix MCP ingest dedup (content-hash id)](tasks/01-fix-mcp-dedup.md) | Correctness | P1 | S | low | — | ☑ done |
| 02 | [Load & enforce seat schema/AGENTS.md](tasks/02-enforce-seat-schema.md) | Governance | P1 | M | med | — | ☑ done |
| 03 | [`wiki_context` tool (raw ranked context, no LLM)](tasks/03-wiki-context-tool.md) | Primitives | P1 | M | low | — | ☑ done |
| 04 | [`wiki_search` + `wiki_get` tools](tasks/04-wiki-search-get-tools.md) | Primitives | P2 | M | low | — | ☑ done |
| 05 | [Semantic retrieval (real embedder + pgvector)](tasks/05-semantic-retrieval.md) | Retrieval | P1 | L | med | 06 | ☑ done |
| 06 | [Vector index lifecycle (rebuild/backfill)](tasks/06-vector-index-lifecycle.md) | Retrieval | P2 | M | med | — | ☑ done |
| 07 | [Concurrency: per-repo write lock](tasks/07-concurrency-write-lock.md) | Reliability | P1 | M | med | — | ☑ done |
| 08 | [Token-budgeted chunked retrieval](tasks/08-token-budget-chunking.md) | Scale | P3 | M | med | 03 | ☑ done |
| 09 | [MCP server hardening (SDK/async/tests)](tasks/09-mcp-server-hardening.md) | Hardening | P3 | L | med | — | ☑ done (FastMCP deferred) |
| 10 | [Provenance + visible degradation](tasks/10-provenance-degradation.md) | Trust | P3 | M | low | 01 | ☑ done |

### Recommended sequencing
**Phase 1 — Correctness & primitives (ship first):** 01 → 02 → 03 → 04
**Phase 2 — Semantic retrieval:** 06 → 05
**Phase 3 — Reliability at concurrency:** 07
**Phase 4 — Scale & hardening:** 08 → 10 → 09

01–04 deliver immediate value for "context for any workflow" and need no embeddings.
05/06 are the biggest retrieval-quality win. 07 is the key reliability gate before
many workflows write concurrently.

---

## Shared definition of done (every task)

- Failing tests written first; implementation makes them pass (TDD).
- `uv run pytest` green, coverage ≥ 80%; `ruff check`, `ruff format --check`, `pyright` clean.
- Public API / tool-schema changes reflected in `test_public_api.py` and `mcp_server.wiki_mcp_tools()`.
- No new hard dependency without it being declared (extras preferred; see `[llm]` precedent).
- Runtime-path changes redeployed to the Hermes venv + seat and verified via `hermes mcp test wiki-engine`.
- `CLAUDE.md` / reference docs updated if behavior or contracts change.

## Architecture invariants (do not regress)

- **Pure-Python engine, no Hermes import.** Judgment is injected via `protocols.py`
  (`Summarizer`/`Embedder`/`Answerer`); LLM calls route through the Hermes proxy only.
- **Markdown is the system of record.** The vector index is *derived* and rebuildable.
- **Every operation ends in `repo.commit(...)`** (injectable committer).
- **Graceful degradation:** a model/proxy/DB outage must degrade, never hard-crash the MCP.

---

## Changelog

<!-- Append one line per completed task: `YYYY-MM-DD  TNN done — <summary>  (commit <sha>)` -->
- 2026-06-12  Roadmap created (tasks 01–10 specced).
- 2026-06-12  T01 done — content-addressed MCP ingest dedup + `status` field; redeployed & verified.
- 2026-06-12  T02 done — MCP ingest/lint load & enforce seat schema/AGENTS.md (off_limits → excluded); seat AGENTS.md key corrected; redeployed & verified.
- 2026-06-12  T03 done — added `wiki_context` tool (raw ranked context + citations, no LLM); 4 tools now; redeployed & verified.
- 2026-06-12  T04 done — added `wiki_search` + `wiki_get` tools; 6 tools now; redeployed & verified.
- 2026-06-12  T06 done — `reindex` rebuild/backfill of the vector index from markdown.
- 2026-06-12  T05 done — semantic retrieval live (fastembed BGE-small dim 384 + pgvector); non-lexical query verified; graceful structural fallback.
- 2026-06-12  T07 done — `WikiRepo.write_lock` (flock) serializes ingest/file writes; parallel-ingest race fixed (was losing 5/8 entries); redeployed.
- 2026-06-12  T08 done — `chunk.py` + chunk-level token-budgeted `wiki_context` (slug/title/heading/text/score); redeployed.
- 2026-06-12  T09 Phase A done — `test_main_server.py` covers `handle_request` (__main__ 0%→66%); timeouts + FastMCP deferred to Phase B.
- 2026-06-12  T10 done — `contributor` provenance on ingest + `mode`/`degraded` flags on ingest/query; redeployed & verified.
- 2026-06-12  T09 Phase B — model-call timeout (`WIKI_LLM_TIMEOUT`, SDK-level) verified bounding a hang; FastMCP migration evaluated and deferred (low benefit / high risk under current single-threaded transport).
