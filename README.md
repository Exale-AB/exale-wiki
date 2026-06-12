# Exale Wiki

The **Self-Improving Knowledge Wiki** — Exale's flagship cross-cutting capability,
extracted from the Exale platform monorepo into its own repository.

The wiki is plain markdown inside each customer's isolated environment, organised in
three layers (raw sources / wiki / schema) with three operations (ingest / query / lint).

## Packages

| Package | What it owns |
|---------|--------------|
| [`wiki-engine`](packages/wiki-engine) | Pure-Python core: repository model, ingest, hybrid retrieval (wikilink + pgvector), query, lint/self-improvement, schema enforcement, HTML render, and the wiki MCP server handlers. No Hermes import. |
| [`wiki-utils`](packages/wiki-utils) | Standard wiki logging helpers used by skill bundles (`log_action`). |
| [`wiki-validation`](packages/wiki-validation) | Seat validation: off-limits, least-privilege, and encryption checks. |

## Development

This is a [uv](https://docs.astral.sh/uv/) workspace. All members install editable
into one shared virtualenv.

```bash
# Install everything (members + dev deps) into .venv
uv sync

# Run the full test suite with the 80% coverage gate
uv run pytest

# Lint & format
uv run ruff check .
uv run ruff format .

# Type-check
uv run pyright
```

Wiki data lives in `$HOME/wiki` at runtime and persists between sessions.

## MCP server

The engine ships a wiki MCP server (`python -m wiki_engine`). Register it with a
local Hermes installation:

```bash
hermes mcp add wiki --command python --args "-m wiki_engine" --env "WIKI_REPO_PATH=$HOME/wiki"
hermes mcp test wiki
```

## Constraints

- **All LLM calls route through Hermes** via `hermes-client` — no direct LLM API calls.
  The engine itself takes `Answerer` / `Summarizer` / `Embedder` protocols so callers
  inject the Hermes-backed implementations.
- **EU data residency only.**
- **Boring stack, on purpose:** Hermes (self-hosted), Postgres + pgvector. No Kubernetes.
