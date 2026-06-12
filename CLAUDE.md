# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

The **Self-Improving Knowledge Wiki** — a pure-Python engine extracted from the Exale
platform monorepo. The wiki is plain markdown inside each customer's isolated seat,
organised in three layers (`raw/` sources, `wiki/` pages, `schema/` rulebook) with three
operations (ingest / query / lint). It ships an MCP server that Hermes agents call.

This is a [uv](https://docs.astral.sh/uv/) workspace with three members under `packages/`:
- `wiki-engine` — the core (repo model, ingest/query/lint, hybrid retrieval, schema, render, MCP handlers). **No Hermes import.**
- `wiki-utils` — `log_action` logging helpers used by seat skill bundles.
- `wiki-validation` — least-privilege scope checks for seat skill bundles.

## Commands

```bash
uv sync                      # install all members + dev deps into shared .venv
uv run pytest                # full suite with the 80% coverage gate (enforced)
uv run pytest packages/wiki-engine/tests/test_query.py            # one file
uv run pytest -k "off_limits"                                     # by name
uv run pytest packages/wiki-engine/tests/test_query.py::test_x    # one test
uv run ruff check .          # lint
uv run ruff format .         # format
uv run pyright               # type-check
python -m wiki_engine        # run the MCP server (reads WIKI_REPO_PATH)
```

Python is pinned to **3.11** to match the Hermes runtime — skill bundles import these
packages inside Hermes' 3.11 interpreter, so the packages must be installed into the
**Hermes venv** (`~/.hermes/hermes-agent/venv`), not just the project `.venv`. Installing
`wiki-engine` alone is not enough; bundles also import `wiki_utils` / `wiki_validation`.

## Architecture

### Dependency-injection seam (the central design)
The engine owns **deterministic bookkeeping**; the **judgment** steps are injected as
`Protocol`s in `protocols.py`:
- `Summarizer.summarize(source)` — used by ingest
- `Embedder.embed(texts)` — used to build the vector index
- `Answerer.answer(question, context)` — formats retrieved context

Callers inject Hermes-backed implementations at runtime; tests inject deterministic
fakes (`fakes.py`). **All LLM/embedding calls route through Hermes** via these seams —
the engine never calls an LLM API directly. The wiki returns **raw context, not
synthesized answers**: the calling agent (Hermes) writes the final natural-language reply.

### Storage: markdown is the system of record
`WikiRepo` (`repo.py`) is a git-versioned markdown store with three dirs: `raw/`
(verbatim sources + `manifest.jsonl`), `wiki/` (pages + reserved `index.md`/`log.md`),
`schema/` (the rulebook). Every operation ends with `repo.commit(...)`. The `committer`
is injectable so tests avoid real git (`_git_commit` is `# pragma: no cover`).

### The three operations
- **ingest** (`ingest.py`): source → summary page + index/log updates. Idempotent via
  `Source.identity()` (sha256 of kind+identifier+text); skips already-seen sources and
  excludes off-limits categories before any work. Single judgment step (summarize) injected.
- **query** (`query.py`): retrieve → format context → optionally file as a new page.
  Returns an `Answer(text, citations, filed_slug)`.
- **lint** (`lint.py`): self-improvement. Pluggable `LintRule`s emit `Violation`s
  (orphaned pages, contradictions, stale sources…); `suggest_refinements` aggregates them
  into `RefinementSuggestion`s for the schema/AGENTS.md.

### Hybrid retrieval (`retrieval.py`)
`Retriever.retrieve()` does **structural navigation first** (token overlap over the index
catalog + wikilink neighbours), then appends **vector recall**. The vector index is
*derived* and rebuildable from markdown. The `VectorStore` protocol has two
implementations: `InMemoryVectorStore` (cosine, for unit tests) and `PgVectorStore`
(psycopg + pgvector, table `wiki_vectors`, cosine `<=>` operator, `# pragma: no cover` —
exercised only against a live Postgres). `ensure_schema()` creates the extension + table.

### Schema enforcement (`schema.py`)
The per-seat `schema/AGENTS.md` is a rulebook: structured rules in YAML frontmatter, prose
guidance below. `WikiSchema` drives allowed source kinds, page-type frontmatter, category
validation, honesty rules, off-limits categories, and lint thresholds. ingest enforces
these before persisting.

### MCP server (`__main__.py` + `mcp_server.py`)
`python -m wiki_engine` runs a stdin/stdout JSON-RPC loop exposing `wiki_query`,
`wiki_ingest`, `wiki_lint`. It wires **`FakeEmbedder` + `FakeVectorStore`** — i.e.
**structural-only retrieval, no database needed** — which is why the MCP works without
Postgres. `WIKI_REPO_PATH` selects the repo.

## Local deployment (native, no Docker)

The running setup treats the local machine as a VPS — no Docker in the path:
- **Native Postgres 16** on `:5432`, database `wiki`, pgvector extension. DSN:
  `postgresql://postgres:localdev@localhost:5432/wiki`.
- **Hermes** (native binary) serves the MCP; all three packages are installed editable in
  its venv.
- The wiki MCP is registered in Hermes' default profile as `wiki-engine`, launched via
  `~/.exale/seats/nandan-exale/bin/wiki-mcp-server.sh` (sets `WIKI_REPO_PATH=~/.exale/wiki`
  and runs the Hermes-venv Python). Verify with `hermes mcp test wiki-engine`.

A parallel `exale-seat-local-*` Docker stack (pgvector on `:5433`, model-mock `:8088`,
hermes `:8642`) may still be running but is **not** used by the native path.

## Gotchas

- **Loose dev-tool pins** (`ruff>=0.8`, `pyright>=1.1.390`): a from-scratch `uv sync` pulls
  newer, stricter versions that surface pre-existing format drift in `wiki-validation` and
  type errors in `wiki-engine/tests/test_query.py`. `uv run pytest` and `ruff check` are
  green; `ruff format --check` and `pyright` are not.
- The `integration` pytest marker is declared but unused — the committed suite is all unit
  tests with no live DB. `PgVectorStore` runtime paths are deliberately excluded from coverage.
- `wiki_utils` is not imported anywhere in the test run, so it contributes nothing to the
  80% coverage gate.

## Constraints

- All LLM calls route through Hermes (`hermes-client`) — no direct LLM API calls.
- EU data residency only.
- Boring stack on purpose: Hermes (self-hosted) + Postgres/pgvector. No Kubernetes.
