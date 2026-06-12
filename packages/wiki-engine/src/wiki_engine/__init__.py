"""Self-Improving Knowledge Wiki engine.

Pure-Python core for the flagship wiki (Architecture §3.1). Roadmap P4a built the
repository model + ingest; P4b adds hybrid retrieval (index/wikilink + pgvector)
and the query operation. Lint/self-improvement (P4c), schema enforcement (P4d),
and render + MCP server (P4e) follow.
"""

from __future__ import annotations

from .errors import IngestError, SchemaError, WikiError
from .fakes import FakeAnswerer, FakeEmbedder, FakeSummarizer
from .ingest import IngestResult, ingest
from .lint import RefinementSuggestion, Violation, lint, suggest_refinements
from .mcp_server import (
    handle_wiki_context,
    handle_wiki_get,
    handle_wiki_ingest,
    handle_wiki_lint,
    handle_wiki_query,
    handle_wiki_search,
    wiki_mcp_tools,
)
from .page import Page
from .protocols import Answerer, Embedder, Summarizer
from .query import Answer, query
from .render import render_wiki_to_html
from .repo import WikiRepo
from .retrieval import (
    InMemoryVectorStore,
    PgVectorStore,
    Retrieved,
    Retriever,
    VectorStore,
)
from .schema import WikiSchema, parse_schema
from .slug import slugify
from .source import Source, SourceKind

__all__ = [
    "Answer",
    "Answerer",
    "Embedder",
    "FakeAnswerer",
    "FakeEmbedder",
    "FakeSummarizer",
    "InMemoryVectorStore",
    "IngestError",
    "IngestResult",
    "Page",
    "PgVectorStore",
    "RefinementSuggestion",
    "Retrieved",
    "Retriever",
    "SchemaError",
    "Source",
    "SourceKind",
    "Summarizer",
    "Violation",
    "VectorStore",
    "WikiError",
    "WikiRepo",
    "WikiSchema",
    "handle_wiki_context",
    "handle_wiki_get",
    "handle_wiki_ingest",
    "handle_wiki_lint",
    "handle_wiki_query",
    "handle_wiki_search",
    "ingest",
    "lint",
    "parse_schema",
    "query",
    "render_wiki_to_html",
    "slugify",
    "suggest_refinements",
    "wiki_mcp_tools",
]
