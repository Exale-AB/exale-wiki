"""Start the wiki MCP server for Hermes agents."""

import json
import os
import sys
from pathlib import Path

from .embed_backends import build_retrieval
from .knowledge_graph import WikiGraph
from .llm_backends import build_judgment
from .mcp_server import TOOL_REGISTRY, ToolContext, wiki_mcp_tools
from .repo import WikiRepo


def main() -> None:
    """Start the wiki MCP server.

    Reads WIKI_REPO_PATH from environment and starts an MCP server
    exposing the wiki tools.
    """
    wiki_repo_path = os.environ.get("WIKI_REPO_PATH", "wiki")
    repo = WikiRepo(Path(wiki_repo_path))

    # Semantic retrieval (local embedder + pgvector) when configured/available,
    # else structural-only fakes — build_retrieval() degrades gracefully. The
    # judgment steps (summarize/answer) come from the Hermes-configured model.
    embedder, vectorstore = build_retrieval()
    summarizer, answerer = build_judgment()

    graph = WikiGraph(path=Path(wiki_repo_path) / "graph.graphml")
    graph.rebuild(repo)

    # Fact extraction: spaCy NER seeds entities, LLM refines into structured facts.
    # Degrades to None (no extraction) if spaCy or openai is missing.
    extractor = None
    try:
        from .extraction import SpacyNerLlmExtractor
        from .llm_backends import OpenAICompatibleClient

        llm_base = os.environ.get("WIKI_LLM_BASE_URL", "http://127.0.0.1:8645/v1")
        llm_model = os.environ.get("WIKI_LLM_MODEL", "minimax/minimax-m3")
        llm_key = os.environ.get("WIKI_LLM_API_KEY", "hermes")
        client = OpenAICompatibleClient(
            base_url=llm_base,
            model=llm_model,
            api_key=llm_key,
        )
        extractor = SpacyNerLlmExtractor(llm_client=client)
    except Exception:
        pass

    ctx = ToolContext(
        repo=repo,
        embedder=embedder,
        vectorstore=vectorstore,
        answerer=answerer,
        summarizer=summarizer,
        extractor=extractor,
        graph=graph,
    )

    # Expose tools via stdin/stdout protocol (standard MCP)
    while True:
        request = None
        try:
            line = sys.stdin.readline()
            if not line:
                break

            request = json.loads(line)
            response = handle_request(request, ctx)
            print(json.dumps(response))
            sys.stdout.flush()

        except json.JSONDecodeError:
            # Ignore malformed JSON
            continue
        except KeyboardInterrupt:
            break
        except Exception as e:
            request_id = None
            if isinstance(request, dict):
                request_id = request.get("id")
            error_response = {
                "jsonrpc": "2.0",
                "error": {"code": -32603, "message": str(e)},
                "id": request_id,
            }
            print(json.dumps(error_response))
            sys.stdout.flush()


def handle_request(request: dict, ctx: ToolContext) -> dict:
    """Handle a single MCP JSON-RPC 2.0 request.

    Dispatch for ``tools/call`` is registry-driven: every tool advertised in
    ``tools/list`` resolves to a handler by construction (see ``TOOL_REGISTRY``).
    """
    method = request.get("method")
    params = request.get("params", {})
    req_id = request.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "result": {
                "protocolVersion": "2024-11-05",
                # Advertise the tools capability so MCP clients (Hermes) query
                # tools/list; an empty capabilities dict makes them discover 0 tools.
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": "wiki-engine",
                    "version": "0.1.0",
                },
            },
            "id": req_id,
        }

    elif method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "result": {"tools": wiki_mcp_tools()},
            "id": req_id,
        }

    elif method == "tools/call":
        tool_name = params.get("name")
        tool = TOOL_REGISTRY.get(tool_name)
        if tool is None:
            return {
                "jsonrpc": "2.0",
                "error": {
                    "code": -32601,
                    "message": f"Unknown tool: {tool_name}",
                },
                "id": req_id,
            }
        try:
            result = tool.handler(ctx, params.get("arguments", {}))
            return {
                "jsonrpc": "2.0",
                "result": {"content": [{"type": "text", "text": json.dumps(result)}]},
                "id": req_id,
            }
        except Exception as e:
            return {
                "jsonrpc": "2.0",
                "error": {"code": -32603, "message": str(e)},
                "id": req_id,
            }

    else:
        return {
            "jsonrpc": "2.0",
            "error": {
                "code": -32601,
                "message": f"Unknown method: {method}",
            },
            "id": req_id,
        }


if __name__ == "__main__":
    main()
