"""Start the wiki MCP server for Hermes agents."""

import json
import os
import sys
from pathlib import Path

from .embed_backends import build_retrieval
from .llm_backends import build_judgment
from .mcp_server import (
    handle_wiki_context,
    handle_wiki_get,
    handle_wiki_ingest,
    handle_wiki_lint,
    handle_wiki_query,
    handle_wiki_search,
    wiki_mcp_tools,
)
from .protocols import Answerer, Embedder, Summarizer
from .repo import WikiRepo
from .retrieval import VectorStore


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

    # Expose tools via stdin/stdout protocol (standard MCP)
    while True:
        request = None
        try:
            line = sys.stdin.readline()
            if not line:
                break

            request = json.loads(line)
            response = handle_request(request, repo, embedder, vectorstore, answerer, summarizer)
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


def handle_request(
    request: dict,
    repo: WikiRepo,
    embedder: Embedder,
    vectorstore: VectorStore,
    answerer: Answerer,
    summarizer: Summarizer | None = None,
) -> dict:
    """Handle a single MCP request.

    Args:
        request: JSON-RPC 2.0 request
        repo: Wiki repository instance
        embedder: Embedder for query operations
        vectorstore: Vector store for semantic search
        answerer: Answerer for synthesizing query answers
        summarizer: Summarizer for ingest page bodies (defaults to FakeSummarizer)

    Returns:
        JSON-RPC 2.0 response
    """
    method = request.get("method")
    params = request.get("params", {})
    req_id = request.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
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
        tool_args = params.get("arguments", {})

        try:
            if tool_name == "wiki_query":
                result = handle_wiki_query(
                    repo=repo,
                    query=tool_args.get("query"),
                    file_as_new_page=tool_args.get("file_as_new_page", False),
                    vectorstore=vectorstore,
                    embedder=embedder,
                    answerer=answerer,
                )
            elif tool_name == "wiki_ingest":
                result = handle_wiki_ingest(
                    repo=repo,
                    source_text=tool_args.get("source_text"),
                    source_url=tool_args.get("source_url"),
                    category=tool_args.get("category"),
                    summarizer=summarizer,
                    embedder=embedder,
                    store=vectorstore,
                    contributor=tool_args.get("contributor"),
                )
            elif tool_name == "wiki_context":
                result = handle_wiki_context(
                    repo=repo,
                    query=tool_args.get("query"),
                    vectorstore=vectorstore,
                    embedder=embedder,
                    k=tool_args.get("k", 5),
                    token_budget=tool_args.get("token_budget", 2000),
                )
            elif tool_name == "wiki_search":
                result = handle_wiki_search(
                    repo=repo,
                    query=tool_args.get("query"),
                    vectorstore=vectorstore,
                    embedder=embedder,
                    k=tool_args.get("k", 10),
                )
            elif tool_name == "wiki_get":
                result = handle_wiki_get(repo=repo, slug=tool_args.get("slug"))
            elif tool_name == "wiki_lint":
                result = handle_wiki_lint(
                    repo=repo,
                    confidence_threshold=tool_args.get("confidence_threshold", 0.5),
                )
            else:
                return {
                    "jsonrpc": "2.0",
                    "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"},
                    "id": req_id,
                }

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
            "error": {"code": -32601, "message": f"Unknown method: {method}"},
            "id": req_id,
        }


if __name__ == "__main__":
    main()
