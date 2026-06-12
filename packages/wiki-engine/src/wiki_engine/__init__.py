"""Self-Improving Knowledge Wiki engine.

Pure-Python core for the flagship wiki (Architecture §3.1). Roadmap P4a built the
repository model + ingest; P4b adds hybrid retrieval (index/wikilink + pgvector)
and the query operation. Lint/self-improvement (P4c), schema enforcement (P4d),
and render + MCP server (P4e) follow.
"""

from __future__ import annotations

from .conflicts import Conflict, Resolution, detect_fact_contradictions
from .errors import IngestError, SchemaError, WikiError
from .fakes import (
    FakeAnswerer,
    FakeConflictResolver,
    FakeEmbedder,
    FakeFactExtractor,
    FakeSummarizer,
)
from .ingest import IngestResult, ingest
from .knowledge_graph import WikiGraph
from .lint import RefinementSuggestion, Violation, fact_contradiction, lint, suggest_refinements
from .mcp_server import (
    handle_wiki_context,
    handle_wiki_get,
    handle_wiki_graph_stats,
    handle_wiki_ingest,
    handle_wiki_lint,
    handle_wiki_query,
    handle_wiki_resolve_conflicts,
    handle_wiki_search,
    wiki_mcp_tools,
)
from .page import Page
from .protocols import Answerer, Embedder, Entity, ExtractedFacts, Fact, FactExtractor, Summarizer
from .query import Answer, query
from .reindex_facts import ReindexFactsResult, reindex_facts
from .render import render_wiki_to_html
from .repo import WikiRepo
from .retrieval import (
    InMemoryVectorStore,
    PgVectorStore,
    Retrieved,
    Retriever,
    VectorStore,
    reciprocal_rank_fusion,
)
from .schema import WikiSchema, parse_schema
from .slug import slugify
from .source import Source, SourceKind

__all__ = [
    "Answer",
    "Answerer",
    "Conflict",
    "Embedder",
    "Entity",
    "ExtractedFacts",
    "Fact",
    "FactExtractor",
    "FakeAnswerer",
    "FakeConflictResolver",
    "FakeEmbedder",
    "FakeFactExtractor",
    "FakeSummarizer",
    "InMemoryVectorStore",
    "IngestError",
    "IngestResult",
    "Page",
    "PgVectorStore",
    "RefinementSuggestion",
    "ReindexFactsResult",
    "Resolution",
    "Retrieved",
    "Retriever",
    "SchemaError",
    "Source",
    "SourceKind",
    "Summarizer",
    "Violation",
    "VectorStore",
    "WikiError",
    "WikiGraph",
    "WikiRepo",
    "WikiSchema",
    "detect_fact_contradictions",
    "fact_contradiction",
    "handle_wiki_context",
    "handle_wiki_get",
    "handle_wiki_graph_stats",
    "handle_wiki_ingest",
    "handle_wiki_lint",
    "handle_wiki_query",
    "handle_wiki_resolve_conflicts",
    "handle_wiki_search",
    "ingest",
    "lint",
    "parse_schema",
    "query",
    "reciprocal_rank_fusion",
    "reindex_facts",
    "render_wiki_to_html",
    "slugify",
    "suggest_refinements",
    "wiki_mcp_tools",
]
