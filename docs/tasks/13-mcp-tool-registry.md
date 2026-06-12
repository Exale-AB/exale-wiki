---
id: T13
title: Collapse MCP tool schema + dispatch + handler into one registry
phase: 5
priority: P3
status: todo
depends_on: []
effort: M
risk: med
files:
  - packages/wiki-engine/src/wiki_engine/mcp_server.py
  - packages/wiki-engine/src/wiki_engine/__main__.py
  - packages/wiki-engine/src/wiki_engine/__init__.py        # fix export drift
  - packages/wiki-engine/tests/test_mcp_schema.py           # extend
  - packages/wiki-engine/tests/test_main_server.py          # keep green / extend
---

# T13 — One record per MCP tool

> Architecture candidate **#3** ("Worth exploring") from the 2026-06-12 review.
> Do this **last** of the three, and only if the tool surface keeps growing — the
> current if/elif is honest at 6 tools. Real payoff, moderate size; resist
> over-abstracting a single-threaded stdin loop.

## Problem (verified)

Each MCP tool is defined in **three disconnected places**:

1. **Schema** — an entry in `wiki_mcp_tools()` (`mcp_server.py:37–188`).
2. **Dispatch + arg-unpack** — a branch in `handle_request`'s if/elif
   (`__main__.py:121–164`), manually pulling `tool_args.get(...)`.
3. **Implementation** — a `handle_wiki_*` function.

Nothing enforces the three agree. A tool advertised in `tools/list` but missing
from dispatch fails only at call time with `-32601`. **Drift already exists:**
`wiki_context`, `wiki_search`, `wiki_get` were added to the schema list and
dispatch but were never re-exported from `__init__.py` (`__init__.py:15–20`
re-exports only the original `handle_wiki_ingest/lint/query` + `wiki_mcp_tools`).

The dispatch is **shallow**: ~60 lines that mostly transcribe argument names that
already exist in the JSON schema.

## Goal / acceptance

- One **registry** is the single source of truth: name → (description, input
  schema, handler).
- `wiki_mcp_tools()` is **derived** from the registry (no hand-maintained second
  list).
- `tools/call` dispatch is a registry lookup; an advertised tool is dispatchable
  **by construction**.
- A test asserts every advertised tool resolves to a handler (catches future
  drift mechanically).
- `__init__.py` export drift fixed (or a test that asserts all `handle_wiki_*`
  are exported).
- **Zero behavioral change** to request/response shapes, error codes, or tool
  schemas (assert via existing `test_mcp_schema` / `test_main_server`).

## Design

### A `Tool` record + registry in `mcp_server.py`

```python
@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[["ToolContext", dict[str, Any]], dict[str, Any]]

def wiki_mcp_tools() -> list[dict[str, Any]]:
    return [{"name": t.name, "description": t.description, "inputSchema": t.input_schema}
            for t in TOOLS]
```

### Normalize handler signature with a `ToolContext`

The handlers today take heterogeneous keyword args (`repo`, `vectorstore`,
`embedder`, `answerer`, `summarizer`, plus per-tool fields). Bundle the injected
collaborators once so every handler has the shape `(ctx, args) -> dict`:

```python
@dataclass(frozen=True)
class ToolContext:
    repo: WikiRepo
    embedder: Embedder
    vectorstore: VectorStore
    answerer: Answerer
    summarizer: Summarizer | None = None
```

Each existing `handle_wiki_*` gets a thin registry adapter that reads its fields
out of `args` and `ctx` (keep the current `handle_*` functions as the typed
implementations — adapters just unpack). Example:

```python
def _query_adapter(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    return handle_wiki_query(
        repo=ctx.repo, query=args.get("query"),
        file_as_new_page=args.get("file_as_new_page", False),
        vectorstore=ctx.vectorstore, embedder=ctx.embedder, answerer=ctx.answerer,
    )

TOOLS = [
    Tool("wiki_query", "...", _QUERY_SCHEMA, _query_adapter),
    Tool("wiki_ingest", "...", _INGEST_SCHEMA, _ingest_adapter),
    Tool("wiki_context", "...", _CONTEXT_SCHEMA, _context_adapter),
    Tool("wiki_search", "...", _SEARCH_SCHEMA, _search_adapter),
    Tool("wiki_get", "...", _GET_SCHEMA, _get_adapter),
    Tool("wiki_lint", "...", _LINT_SCHEMA, _lint_adapter),
]
_BY_NAME = {t.name: t for t in TOOLS}
```

### Shrink `__main__.handle_request`

The `tools/call` branch becomes:

```python
tool = _BY_NAME.get(params.get("name"))
if tool is None:
    return _error(req_id, -32601, f"Unknown tool: {params.get('name')}")
try:
    result = tool.handler(ctx, params.get("arguments", {}))
    return {"jsonrpc": "2.0", "result": {"content": [{"type": "text", "text": json.dumps(result)}]}, "id": req_id}
except Exception as e:
    return _error(req_id, -32603, str(e))
```

`main()` builds one `ToolContext` from `build_retrieval()` + `build_judgment()`
and passes it down. `initialize` / `tools/list` branches are unchanged.

> Keep the JSON-RPC envelope, error codes (`-32601` unknown method/tool,
> `-32603` internal), and the malformed-JSON / `KeyboardInterrupt` handling in
> `main()` exactly as-is.

## Test plan (TDD — write these failing first)

In `test_mcp_schema.py`:

- `test_every_advertised_tool_is_dispatchable` — for each `t["name"]` in
  `wiki_mcp_tools()`, assert `name in _BY_NAME` (the anti-drift guard; this is
  the whole point).
- `test_tools_list_matches_registry` — `wiki_mcp_tools()` names == `[t.name for t
  in TOOLS]`, in order.
- `test_all_handlers_exported` — every `handle_wiki_*` (or every registry tool)
  is reachable from the package's public surface (closes the `__init__` drift).

In `test_main_server.py` (keep/extend): the existing per-tool `tools/call`
request→response assertions must pass unchanged against the registry dispatch
(behavioral-equivalence proof).

Update `test_public_api.py` if `Tool` / `ToolContext` join the public API
(prefer keeping them internal unless a caller needs them).

## Verification

```bash
uv run pytest packages/wiki-engine/tests/test_mcp_schema.py packages/wiki-engine/tests/test_main_server.py -v
uv run pytest
uv run ruff check . && uv run ruff format --check . && uv run pyright
```

Runtime-path change → **redeploy** to the Hermes venv and run `hermes mcp test
wiki-engine`; smoke each tool (`wiki_query`, `wiki_ingest`, `wiki_context`,
`wiki_search`, `wiki_get`, `wiki_lint`) once through the launcher.

## Rollback

Self-contained in `mcp_server.py` + `__main__.py`. Revert both; the registry is
additive and the old if/elif can be restored from git.

## Notes

- This is a **mechanical, behavior-preserving** refactor — lean on
  `test_main_server` as the equivalence oracle. If it stays green, the wire
  contract is unchanged.
- Don't reach for FastMCP/async here; T09 Phase B already evaluated and deferred
  that under the current single-threaded transport.
- Folds in the review's *Speculative* note: the per-tool retrieval-context
  duplication (`Retriever(...)` rebuilt in `handle_wiki_query/context/search`) can
  move onto `ToolContext` (e.g. a cached `ctx.retriever`) once handlers share a
  context — optional, do only if it stays simple.

## Status log
- _(todo)_
