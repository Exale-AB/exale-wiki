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

The derived knowledge graph lives at **`repo.graph_path`** — the repo root, beside
`wiki/` rather than inside it, because `wiki/` is the system of record and the graph is
rebuildable from page frontmatter. **`WikiRepo` owns that path so two callers cannot
disagree about it again**: the MCP server and the reindex CLI each computed it
themselves and wrote different files, and nothing ever read the CLI's copy. It
accumulated stale vertices indefinitely and reappeared on every run after being deleted.
`prune_legacy_graph()` removes the orphan and both entry points call it.

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

### Retry policy is per-caller (`llm_backends.py`)
`OpenAICompatibleClient` defaults to **`max_retries=0`**, because the MCP server is a
single-threaded loop with an agent waiting: a retry storm there stacks timeout latency
onto every degraded call. Batch callers have no latency budget, so `reindex_facts` passes
`BATCH_MAX_RETRIES` explicitly — four transient timeouts on a seat left twelve pages
unconverted, which is exactly what a retry fixes. `WIKI_LLM_MAX_RETRIES` sets the default
without a code change; an explicit argument wins, because the caller knows whether it is
interactive and the environment does not.

Retries go through the **Hermes proxy** like every other model call — the engine still
never talks to an LLM vendor directly. The SDK owns the backoff and retries only what can
succeed on a second attempt (connection errors, timeouts, 429, 5xx); a 400 is not retried
because it would fail identically.

### Bilingual NER (`language.py`)
Seats declare `languages: [sv, en]`, so `SpacyNerLlmExtractor` detects each
document's language and loads `sv_core_news_md` or `en_core_web_md` rather than
always English. Detection is a deliberate zero-dependency heuristic (diacritics
+ disjoint stopword sets) — the sv/en decision is binary, and the engine core
stays installable with no extras. Both models' labels are normalised to one
canonical vocabulary so the graph holds one type per real-world concept;
`canonical_entity_type` owns that map. A missing model degrades to the default
language with one warning; a missing *default* model raises, since there is
nothing left to degrade to.

⚠️ **Both seats currently have only `en_core_web_sm`.** The `md` tier is chosen
because Swedish NER scores F1 0.95 on it against 0.75 on `sm` — but until the
wiki-mcp playbook in exale-infra downloads `en_core_web_md` and
`sv_core_news_md`, fact extraction on a seat will raise rather than degrade.
Ship the playbook change first. Model sizes: 54 MB + 72 MB per seat.

Detection is weakest on very short text, which includes query-time extraction in
`retrieval.py`.

### Relabelling persisted types (`relabel.py`)
`python -m wiki_engine.relabel [--write]` maps entity and fact types already on
disk onto the current canonical vocabulary. No model, no tokens, idempotent, and
it imports nothing optional so it runs on a seat with neither spaCy nor an LLM
client.

It exists because **`reindex_facts --force` is the wrong tool for a vocabulary
change.** It spends tokens re-extracting content that has not changed, and a page
whose extraction fails is left untouched by design (see Gotchas), so its old
types survive the run. Historically it was worse: a failed extraction and an
empty one were indistinguishable, so twelve pages on one seat kept stale records
through a full `--force` run while their mtimes claimed otherwise. That part is
fixed; the token cost and the untouched-on-failure behaviour are not bugs.

Reach for `relabel` after any change to the canonical map. Reach for
`reindex_facts` only when you actually want new extraction.

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

## The docs harness

`tests/test_docs_harness.py` checks this file and `README.md` against the code:
referenced paths and `wiki_engine.*` modules exist, the README covers every
workspace member, advertised extras are real, and the coverage gate, dev-tool
pins and Python pin quoted in prose match `pyproject.toml`. It also enforces two
claims made above rather than leaving them as prose — no Hermes import, and the
optional extras (`openai`, `fastembed`, `spacy`) imported lazily so
`import wiki_engine` works without them.

It exists because three sibling repos use this engine by reading these two files
rather than the source. **If you move a module or change a tool setting, update
the docs in the same commit** — the harness will fail otherwise, which is the
point.

Design notes under `docs/` are checked more loosely: they legitimately cite files
in other repos and in the papers they port from, so only paths anchored at a real
top-level directory of this repo are verified. A doc describing an abandoned
design is legitimate history — put `HISTORICAL RECORD` in its first lines,
pointing at what replaced it, and the currency checks skip it.

## Gotchas

- **`reindex_facts --force` clears, and that is deliberate.** Force means
  re-extract from scratch, so a page whose extraction returns nothing loses its
  records. A page whose extraction *fails* is left untouched instead and counted
  in `ReindexFactsResult.failed` — a timeout must not delete real facts. The two
  used to be the same empty tuple, which is how twelve pages on a seat survived a
  full `--force` run with stale records and fresh mtimes.
- **`ExtractedFacts.relations_failed`** carries that distinction. It defaults to
  `False`, so external `FactExtractor` implementations need no change.

- **Dev-tool pins are exact** (`ruff==0.16.1`, `pyright==1.1.411`) so output is stable
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
