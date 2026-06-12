"""Start the wiki MCP server for Hermes agents."""

import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from .mcp_server import (
    handle_wiki_ingest,
    handle_wiki_lint,
    handle_wiki_query,
    wiki_mcp_tools,
)
from .protocols import Answerer, Embedder
from .repo import WikiRepo
from .retrieval import Retrieved, VectorStore


class FakeEmbedder(Embedder):
    """Dummy embedder that returns zero vectors (for structural search only)."""

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Return dummy embeddings."""
        return [[0.0] * 768 for _ in texts]


class FakeVectorStore(VectorStore):
    """Dummy vector store that returns no results (structural search only)."""

    def upsert(self, slug: str, vector: Sequence[float]) -> None:
        """No-op."""
        pass

    def search(self, vector: Sequence[float], k: int) -> list[Retrieved]:
        """Return empty results (all search via structure only)."""
        return []


class RobustSummarizer(Answerer):
    """Return raw wiki context for the agent to synthesize from.

    The agent (Hermes) is responsible for the final natural-language response.
    This class just formats the retrieved context in a way the agent can consume.
    """

    def answer(self, question: str, context: Sequence[str]) -> str | None:
        """Return the raw context for the agent to synthesize from.

        Args:
            question: The user's query
            context: List of page content snippets

        Returns:
            Raw context formatted with separators, or None if no context
        """
        if not context or not any(context):
            return None

        # Filter empty/whitespace contexts
        valid_content = [c for c in context if c and c.strip()]
        if not valid_content:
            return None

        # Return raw context with separators for agent consumption
        return f"Question: {question}\n\n" + "\n\n---\n\n".join(valid_content)


def main() -> None:
    """Start the wiki MCP server.

    Reads WIKI_REPO_PATH from environment and starts an MCP server
    exposing wiki_query, wiki_ingest, and wiki_lint tools.
    """
    wiki_repo_path = os.environ.get("WIKI_REPO_PATH", "wiki")
    repo = WikiRepo(Path(wiki_repo_path))

    # Initialize components for MCP handlers
    embedder = FakeEmbedder()
    vectorstore = FakeVectorStore()
    answerer = RobustSummarizer()

    # Expose tools via stdin/stdout protocol (standard MCP)
    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                break

            request = json.loads(line)
            response = handle_request(request, repo, embedder, vectorstore, answerer)
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
) -> dict:
    """Handle a single MCP request.

    Args:
        request: JSON-RPC 2.0 request
        repo: Wiki repository instance
        embedder: Embedder for query operations
        vectorstore: Vector store for semantic search
        answerer: Answerer for returning raw context to the agent

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
                )
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
