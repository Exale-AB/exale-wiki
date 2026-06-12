"""Unit tests for the MCP request dispatcher (T09).

`__main__.handle_request` is the deployed entrypoint's core and was previously
uncovered. These exercise every method/tool path plus the error branches.
"""

from pathlib import Path

from wiki_engine.__main__ import handle_request
from wiki_engine.fakes import FakeAnswerer, FakeEmbedder, FakeSummarizer
from wiki_engine.mcp_server import ToolContext
from wiki_engine.page import Page
from wiki_engine.repo import WikiRepo
from wiki_engine.retrieval import NullVectorStore


def _call(tmp_path: Path, request: dict) -> dict:
    repo = WikiRepo.init(tmp_path, committer=lambda _r, _m: None)
    repo.write_page(Page(slug="p", frontmatter={"title": "P"}, body="alpha bravo"))
    repo.write_index("# Index\n\n## X\n- [[P]] (p) — alpha bravo\n")
    ctx = ToolContext(
        repo=repo,
        embedder=FakeEmbedder(),
        vectorstore=NullVectorStore(),
        answerer=FakeAnswerer(),
        summarizer=FakeSummarizer(),
    )
    return handle_request(request, ctx)


def _tool(tmp_path: Path, name: str, arguments: dict, req_id: int = 9) -> dict:
    return _call(
        tmp_path,
        {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
    )


def _payload(resp: dict) -> dict:
    import json

    return json.loads(resp["result"]["content"][0]["text"])


def test_initialize_returns_server_info(tmp_path: Path):
    resp = _call(tmp_path, {"id": 1, "method": "initialize"})
    assert resp["result"]["serverInfo"]["name"] == "wiki-engine"
    assert resp["id"] == 1


def test_tools_list_lists_all_tools(tmp_path: Path):
    resp = _call(tmp_path, {"id": 2, "method": "tools/list"})
    names = {t["name"] for t in resp["result"]["tools"]}
    assert names == {
        "wiki_query",
        "wiki_ingest",
        "wiki_context",
        "wiki_search",
        "wiki_get",
        "wiki_lint",
        "wiki_graph_stats",
        "wiki_resolve_conflicts",
    }


def test_dispatch_query(tmp_path: Path):
    assert "citations" in _payload(_tool(tmp_path, "wiki_query", {"query": "alpha"}))


def test_dispatch_context(tmp_path: Path):
    assert "context" in _payload(_tool(tmp_path, "wiki_context", {"query": "alpha"}))


def test_dispatch_search(tmp_path: Path):
    assert "results" in _payload(_tool(tmp_path, "wiki_search", {"query": "alpha"}))


def test_dispatch_get(tmp_path: Path):
    assert _payload(_tool(tmp_path, "wiki_get", {"slug": "p"}))["found"] is True


def test_dispatch_ingest(tmp_path: Path):
    payload = _payload(
        _tool(tmp_path, "wiki_ingest", {"source_text": "new note", "category": "note"})
    )
    assert payload["status"] == "created"


def test_dispatch_lint(tmp_path: Path):
    payload = _payload(_tool(tmp_path, "wiki_lint", {}))
    assert "violations" in payload and "suggestions" in payload


def test_unknown_tool_returns_error(tmp_path: Path):
    resp = _tool(tmp_path, "wiki_nope", {})
    assert resp["error"]["code"] == -32601


def test_unknown_method_returns_error(tmp_path: Path):
    resp = _call(tmp_path, {"id": 7, "method": "no/such"})
    assert resp["error"]["code"] == -32601


def test_handler_exception_becomes_jsonrpc_error(tmp_path: Path):
    # Neither source_text nor source_url -> ValueError inside the handler.
    resp = _tool(tmp_path, "wiki_ingest", {"category": "note"})
    assert resp["error"]["code"] == -32603
