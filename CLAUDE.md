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

## Exale repositories (organization map)

Exale AB (https://github.com/Exale-AB) builds its AI-employee platform across **four sibling
repositories**, cloned side by side on the dev machine. When working in any one of them, assume
the other three also exist locally at the paths below — features often span more than one.

| Repo (GitHub) | Local path | Role |
|---|---|---|
| `Exale-AB/exale-wiki` | `~/projects/exale` | **Wiki engine** — pure-Python Self-Improving Knowledge Wiki; ships the `wiki-engine` MCP server. No Hermes import. |
| `Exale-AB/exale-hermes` | `~/projects/exale-hermes` | **Agent skills** — Hermes skill bundles + libraries (inbox-triage, follow-up, knowledge-wiki, pipeline-watchdog…) orchestrated over MCP. |
| `Exale-AB/exale-infra` | `~/projects/exale-infra` | **Infrastructure** — per-seat VPS provisioning, deployment (Hetzner/Ansible), and studio operator tooling. |
| `Exale-AB/exale-local` | `~/projects/exale-local/myagent` | **Local seat** — a runnable Hermes deployment seat wiring engine + bundles on a local machine treated as a VPS. |

How they fit together: `exale-infra` provisions a **seat** (a VPS running one **Hermes** agent);
that agent loads bundles from `exale-hermes`, which call the `wiki-engine` MCP server from
`exale-wiki` and install its packages into the Hermes venv; `exale-local` is a concrete seat for
local dev/demo using the same wiring on localhost. The wiki **data** (markdown knowledge base +
graph) is not in this org — it lives per-seat at `~/.exale` as its own git-versioned store.

**You are currently in: `Exale-AB/exale-wiki` (this is the wiki engine repo).**

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

- **Dev-tool pins are exact** (`ruff==0.15.17`, `pyright==1.1.410`) so output is stable
  across machines; bump them deliberately. The full gate is green: `uv run pytest`,
  `ruff check`, `ruff format --check`, and `pyright` (0 errors — only a benign
  `reportMissingModuleSource` warning for the optional, lazily-imported `requests` in
  `lint.py`'s `dead_source_urls` rule).
- The `integration` pytest marker is declared but unused — the committed suite is all unit
  tests with no live DB. `PgVectorStore` runtime paths are deliberately excluded from coverage.
- `wiki_utils` is not imported anywhere in the test run, so it contributes nothing to the
  80% coverage gate.

## Constraints

- All LLM calls route through Hermes (`hermes-client`) — no direct LLM API calls.
- EU data residency only.
- Boring stack on purpose: Hermes (self-hosted) + Postgres/pgvector. No Kubernetes.

## graphify

This project has a graphify knowledge graph at graphify-out/.

Rules:
- Before answering architecture or codebase questions, read graphify-out/GRAPH_REPORT.md for god nodes and community structure
- If graphify-out/wiki/index.md exists, navigate it instead of reading raw files
- For cross-module "how does X relate to Y" questions, prefer `graphify query "<question>"`, `graphify path "<A>" "<B>"`, or `graphify explain "<concept>"` over grep — these traverse the graph's EXTRACTED + INFERRED edges instead of scanning files
- After modifying code files in this session, run `graphify update .` to keep the graph current (AST-only, no API cost)
