"""MCP server exposing wiki operations (ingest, query, lint) to Hermes agents."""

from __future__ import annotations

from typing import Any

from .protocols import Answerer, Embedder
from .repo import WikiRepo
from .retrieval import Retriever, VectorStore


def wiki_mcp_tools() -> list[dict[str, Any]]:
    """Return MCP tool definitions for wiki operations.

    Tools:
    - wiki_query: Query the wiki and retrieve grounded answers
    - wiki_ingest: Ingest a new source into the wiki
    - wiki_lint: Run lint and get violations + suggestions

    Each tool is a JSON Schema compatible MCP tool definition.
    """
    return [
        {
            "name": "wiki_query",
            "description": "Query the Knowledge Wiki and retrieve grounded answers with citations",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "The query to search the wiki for (e.g., 'How to set up Gmail?')"
                        ),
                    },
                    "file_as_new_page": {
                        "type": "boolean",
                        "description": (
                            "If true, file the answer as a new wiki page ('never asked twice')"
                        ),
                        "default": False,
                    },
                },
                "required": ["query"],
            },
        },
        {
            "name": "wiki_ingest",
            "description": "Ingest a new source into the Knowledge Wiki (text, URL, or message)",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "source_text": {
                        "type": "string",
                        "description": (
                            "The text content to ingest (e.g., email body, "
                            "note, or document excerpt)"
                        ),
                    },
                    "source_url": {
                        "type": "string",
                        "description": "A URL to fetch and ingest as a source",
                    },
                    "category": {
                        "type": "string",
                        "description": (
                            "The wiki category to ingest into (e.g., 'email', 'process', 'faq')"
                        ),
                    },
                },
                "required": ["category"],
                "anyOf": [
                    {"required": ["source_text"]},
                    {"required": ["source_url"]},
                ],
            },
        },
        {
            "name": "wiki_lint",
            "description": (
                "Run lint checks on the wiki and retrieve violations + "
                "schema-refinement suggestions"
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "confidence_threshold": {
                        "type": "number",
                        "description": (
                            "Minimum confidence (0.0–1.0) for violations to report (default: 0.5)"
                        ),
                        "default": 0.5,
                    },
                },
            },
        },
    ]


def handle_wiki_query(
    repo: WikiRepo,
    query: str,
    file_as_new_page: bool,
    vectorstore: VectorStore,
    embedder: Embedder,
    answerer: Answerer,
) -> dict[str, Any]:
    """Execute a wiki query and return the answer with citations.

    Args:
        repo: The wiki repository
        query: The query string
        file_as_new_page: If true, file the answer as a new page
        vectorstore: Vector store for semantic search
        embedder: Embedder for creating vectors
        answerer: Answerer for generating answers from retrieved context

    Returns:
        Dict with "answer" (str) and "citations" (list of page slugs)
    """
    from .query import query as query_wiki

    retriever = Retriever(repo=repo, store=vectorstore, embedder=embedder)

    answer = query_wiki(
        question=query,
        retriever=retriever,
        answerer=answerer,
        repo=repo,
        file_as="Query Result" if file_as_new_page else None,
    )

    return {
        "answer": answer.text,
        "citations": list(answer.citations),
    }


def handle_wiki_ingest(
    repo: WikiRepo,
    source_text: str | None,
    source_url: str | None,
    category: str,
    schema: Any = None,
) -> dict[str, Any]:
    """Ingest a source into the wiki.

    Args:
        repo: The wiki repository
        source_text: Raw text to ingest
        source_url: URL to ingest from
        category: Wiki category
        schema: WikiSchema for validation (optional)

    Returns:
        Dict with "slug", "title", and "sources_merged" count
    """
    from .fakes import FakeSummarizer
    from .ingest import ingest
    from .schema import WikiSchema
    from .source import Source, SourceKind

    # Determine source kind and create Source
    if source_text:
        source = Source(
            kind=SourceKind.MESSAGE,
            identifier=f"mcp-text-{id(source_text)}",
            text=source_text,
            title=source_text.split("\n")[0][:80],
            categories=(category,),
        )
    elif source_url:
        source = Source(
            kind=SourceKind.URL,
            identifier=source_url,
            text=source_url,
            title=source_url[:80],
            categories=(category,),
        )
    else:
        raise ValueError("Either source_text or source_url must be provided")

    # Use provided schema or create a default one
    if schema is None:
        schema = WikiSchema(default_category=category)

    # Use FakeSummarizer for now (no LLM available in handler)
    result = ingest(
        source=source,
        repo=repo,
        schema=schema,
        summarizer=FakeSummarizer(),
    )

    # Read the page to get the sources_merged count
    if result.slug:
        page = repo.read_page(result.slug)
        sources_merged = len(page.frontmatter.get("sources", [])) if page else 1
    else:
        sources_merged = 0

    return {
        "slug": result.slug or "",
        "title": source.title,
        "sources_merged": sources_merged,
    }


def handle_wiki_lint(
    repo: WikiRepo,
    confidence_threshold: float = 0.5,
    schema: Any = None,
) -> dict[str, Any]:
    """Run lint on the wiki and return violations + suggestions.

    Args:
        repo: The wiki repository
        confidence_threshold: Minimum confidence (0.0–1.0) for violations
        schema: WikiSchema for lint configuration (optional)

    Returns:
        Dict with "violations" (list of dicts) and "suggestions" (list of dicts)
    """
    from .lint import lint, suggest_refinements
    from .schema import WikiSchema

    # Use provided schema or create a default one
    if schema is None:
        schema = WikiSchema()

    violations_list = lint(repo, schema=schema)
    violations_filtered = [v for v in violations_list if v.confidence >= confidence_threshold]

    suggestions = suggest_refinements(violations_filtered, repo)

    return {
        "violations": [
            {
                "rule": v.rule,
                "confidence": v.confidence,
                "message": v.message,
                "affected_pages": v.affected_pages,
            }
            for v in violations_filtered
        ],
        "suggestions": [
            {
                "violation_pattern": s.violation_pattern,
                "suggested_change": s.suggested_change,
                "confidence": s.confidence,
            }
            for s in suggestions
        ],
    }
