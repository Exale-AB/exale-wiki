"""MCP server exposing wiki operations (ingest, query, lint) to Hermes agents."""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .protocols import Answerer, Embedder, Summarizer
from .repo import WikiRepo
from .retrieval import Retriever, VectorStore

if TYPE_CHECKING:
    from .schema import WikiSchema


def load_seat_schema(repo: WikiRepo) -> WikiSchema:
    """Load the seat rulebook from ``schema/AGENTS.md``.

    Falls back to a default ``WikiSchema`` (and warns) when the file is absent or
    malformed, so a missing/broken rulebook degrades rather than crashing the MCP.
    """
    from .schema import WikiSchema, parse_schema

    path = repo.schema_dir / "AGENTS.md"
    try:
        if path.exists():
            return parse_schema(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - degrade, never crash the MCP
        print(
            f"[wiki_engine.mcp_server] schema load failed ({exc}); using default schema",
            file=sys.stderr,
            flush=True,
        )
    return WikiSchema()


@dataclass(frozen=True)
class ToolContext:
    """Bundled collaborators shared by every MCP tool handler."""

    repo: WikiRepo
    embedder: Embedder
    vectorstore: VectorStore
    answerer: Answerer
    summarizer: Summarizer | None = None


@dataclass(frozen=True)
class Tool:
    """Single source of truth for one MCP tool: schema + handler together."""

    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[[ToolContext, dict[str, Any]], dict[str, Any]]


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
    from .llm_backends import HermesAnswerer
    from .query import query as query_wiki

    retriever = Retriever(repo=repo, store=vectorstore, embedder=embedder)

    answer = query_wiki(
        question=query,
        retriever=retriever,
        answerer=answerer,
        repo=repo,
        file_as="Query Result" if file_as_new_page else None,
    )

    model_backed = isinstance(answerer, HermesAnswerer)
    return {
        "answer": answer.text,
        "citations": list(answer.citations),
        "mode": "model" if model_backed else "fake",
        "degraded": not model_backed,
    }


_CHARS_PER_TOKEN = 4  # crude estimate; T08 replaces this with real chunk-level budgeting


def handle_wiki_context(
    repo: WikiRepo,
    query: str,
    *,
    vectorstore: VectorStore,
    embedder: Embedder,
    k: int = 5,
    token_budget: int = 2000,
) -> dict[str, Any]:
    """Return ranked raw context for a query — no synthesis, no LLM call.

    Retrieves the top pages, packs their bodies under ``token_budget`` (preferring
    whole pages, in rank order), and returns the snippets plus their citations. This
    is the cheap "give my workflow grounding context" primitive; ``wiki_query`` is
    for when you want a synthesized answer instead.

    Returns:
        Dict with "context" (list of {slug, title, heading, text, score}) and
        "citations" (unique slugs, in order).
    """
    from .chunk import chunk_page

    retriever = Retriever(repo=repo, store=vectorstore, embedder=embedder)
    slugs = retriever.retrieve(query, k=k)
    tokens = {t for t in query.lower().split() if t}

    budget_chars = max(0, token_budget) * _CHARS_PER_TOKEN
    context: list[dict[str, Any]] = []
    used = 0
    for slug in slugs:
        page = repo.read_page(slug)
        if page is None:
            continue
        title = page.frontmatter.get("title", slug)
        for ch in chunk_page(slug, page.body):
            if context and used + len(ch.text) > budget_chars:
                return _context_result(context)
            text = ch.text
            if not context and budget_chars and len(text) > budget_chars:
                text = text[:budget_chars]  # always return at least the top chunk
            score = sum(1 for t in tokens if t in text.lower())
            context.append(
                {"slug": slug, "title": title, "heading": ch.heading, "text": text, "score": score}
            )
            used += len(text)

    return _context_result(context)


def _context_result(context: list[dict[str, Any]]) -> dict[str, Any]:
    citations: list[str] = []
    for item in context:
        if item["slug"] not in citations:
            citations.append(item["slug"])
    return {"context": context, "citations": citations}


def handle_wiki_search(
    repo: WikiRepo,
    query: str,
    *,
    vectorstore: VectorStore,
    embedder: Embedder,
    k: int = 10,
) -> dict[str, Any]:
    """Ranked hits with catalog metadata — no synthesis, no page bodies.

    The cheap "does a page about X already exist?" / browse primitive. Pairs with
    wiki_ingest: search first, only ingest when nothing relevant exists.

    Returns:
        Dict with "results": [{slug, title, summary, category, score}] (ranked).
    """
    from . import catalog

    retriever = Retriever(repo=repo, store=vectorstore, embedder=embedder)
    slugs = retriever.retrieve(query, k=k)
    entries = {e.slug: e for e in catalog.parse_index(repo.read_index())}
    tokens = {t for t in query.lower().split() if t}

    results: list[dict[str, Any]] = []
    for slug in slugs:
        entry = entries.get(slug)
        if entry is not None:
            title, summary, category = entry.title, entry.summary, entry.category
        else:
            page = repo.read_page(slug)
            title = page.frontmatter.get("title", slug) if page else slug
            summary = ""
            category = page.frontmatter.get("category", "") if page else ""
        score = sum(1 for t in tokens if t in f"{title} {summary}".lower())
        results.append(
            {"slug": slug, "title": title, "summary": summary, "category": category, "score": score}
        )

    return {"results": results}


def handle_wiki_get(repo: WikiRepo, slug: str) -> dict[str, Any]:
    """Fetch a single page by slug (full frontmatter + body), or report not-found."""
    page = repo.read_page(slug)
    if page is None:
        return {"found": False, "slug": slug}
    return {
        "found": True,
        "slug": page.slug,
        "title": page.frontmatter.get("title", page.slug),
        "frontmatter": dict(page.frontmatter),
        "body": page.body,
    }


def handle_wiki_ingest(
    repo: WikiRepo,
    source_text: str | None,
    source_url: str | None,
    category: str,
    schema: Any = None,
    summarizer: Summarizer | None = None,
    embedder: Embedder | None = None,
    store: VectorStore | None = None,
    contributor: str | None = None,
) -> dict[str, Any]:
    """Ingest a source into the wiki.

    Args:
        repo: The wiki repository
        source_text: Raw text to ingest
        source_url: URL to ingest from
        category: Wiki category
        schema: WikiSchema for validation (optional)
        summarizer: Summarizer for the page body (defaults to FakeSummarizer)
        embedder: Embedder for the vector index (optional; with ``store``)
        store: Vector store to upsert the page embedding into (optional)

    Returns:
        Dict with "slug", "title", "status", and "sources_merged" count
    """
    import hashlib

    from .fakes import FakeSummarizer
    from .ingest import ingest
    from .source import Source, SourceKind

    # Determine source kind and create Source
    if source_text:
        # Content-addressed identifier so re-ingesting identical text dedupes.
        # (Previously used id(source_text), a memory address, which broke dedup.)
        text_digest = hashlib.sha256(source_text.encode("utf-8")).hexdigest()[:16]
        source = Source(
            kind=SourceKind.MESSAGE,
            identifier=f"text:{text_digest}",
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

    # Load the seat rulebook (off_limits, allowed kinds, honesty) and keep the
    # per-ingest category as the page's category by overriding default_category.
    if schema is None:
        from dataclasses import replace

        schema = replace(load_seat_schema(repo), default_category=category)

    from .llm_backends import HermesSummarizer

    active_summarizer = summarizer or FakeSummarizer()
    off_limits = list(schema.honesty_rules.get("off_limits_categories", []))
    result = ingest(
        source=source,
        repo=repo,
        schema=schema,
        summarizer=active_summarizer,
        off_limits=off_limits,
        embedder=embedder,
        store=store,
        contributor=contributor,
    )

    # Read the page to get the sources_merged count
    if result.slug:
        page = repo.read_page(result.slug)
        sources_merged = len(page.frontmatter.get("sources", [])) if page else 1
    else:
        sources_merged = 0

    if result.excluded:
        status = "excluded"
    elif result.skipped:
        status = "skipped"
    elif result.created:
        status = "created"
    elif result.updated:
        status = "updated"
    else:
        status = "unknown"

    return {
        "slug": result.slug or "",
        "title": source.title,
        "status": status,
        "sources_merged": sources_merged,
        "mode": "model" if isinstance(active_summarizer, HermesSummarizer) else "fake",
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

    # Use the seat rulebook (thresholds, honesty rules) unless one is injected.
    if schema is None:
        schema = load_seat_schema(repo)

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


# ── Tool registry: single source of truth for name → schema → handler ──────


def _query_adapter(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    return handle_wiki_query(
        repo=ctx.repo,
        query=args["query"],
        file_as_new_page=args.get("file_as_new_page", False),
        vectorstore=ctx.vectorstore,
        embedder=ctx.embedder,
        answerer=ctx.answerer,
    )


def _ingest_adapter(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    return handle_wiki_ingest(
        repo=ctx.repo,
        source_text=args.get("source_text"),
        source_url=args.get("source_url"),
        category=args["category"],
        summarizer=ctx.summarizer,
        embedder=ctx.embedder,
        store=ctx.vectorstore,
        contributor=args.get("contributor"),
    )


def _context_adapter(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    return handle_wiki_context(
        repo=ctx.repo,
        query=args["query"],
        vectorstore=ctx.vectorstore,
        embedder=ctx.embedder,
        k=args.get("k", 5),
        token_budget=args.get("token_budget", 2000),
    )


def _search_adapter(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    return handle_wiki_search(
        repo=ctx.repo,
        query=args["query"],
        vectorstore=ctx.vectorstore,
        embedder=ctx.embedder,
        k=args.get("k", 10),
    )


def _get_adapter(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    return handle_wiki_get(repo=ctx.repo, slug=args["slug"])


def _lint_adapter(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    return handle_wiki_lint(
        repo=ctx.repo,
        confidence_threshold=args.get("confidence_threshold", 0.5),
    )


TOOLS: tuple[Tool, ...] = (
    Tool(
        name="wiki_query",
        description=("Query the Knowledge Wiki and retrieve grounded answers with citations"),
        input_schema={
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
        handler=_query_adapter,
    ),
    Tool(
        name="wiki_ingest",
        description=("Ingest a new source into the Knowledge Wiki (text, URL, or message)"),
        input_schema={
            "type": "object",
            "properties": {
                "source_text": {
                    "type": "string",
                    "description": (
                        "The text content to ingest (e.g., email body, note, or document excerpt)"
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
                "contributor": {
                    "type": "string",
                    "description": (
                        "Optional: which workflow/bundle/person added this"
                        " source (recorded as provenance on the page)"
                    ),
                },
            },
            "required": ["category"],
            "anyOf": [
                {"required": ["source_text"]},
                {"required": ["source_url"]},
            ],
        },
        handler=_ingest_adapter,
    ),
    Tool(
        name="wiki_context",
        description=(
            "Retrieve ranked raw context (page snippets + citations) for a"
            " query WITHOUT synthesizing an answer — fast grounding material"
            " for a workflow to reason over itself. Use this instead of"
            " wiki_query when you want context, not a finished answer."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "What to retrieve context about",
                },
                "k": {
                    "type": "integer",
                    "description": "Max pages to consider (default: 5)",
                    "default": 5,
                },
                "token_budget": {
                    "type": "integer",
                    "description": ("Approx token cap on returned context (default: 2000)"),
                    "default": 2000,
                },
            },
            "required": ["query"],
        },
        handler=_context_adapter,
    ),
    Tool(
        name="wiki_search",
        description=(
            "Ranked search hits (slug, title, summary, score) with NO page"
            " bodies and no synthesis — cheap way to check whether a page"
            " already exists or to browse. Use before wiki_ingest to avoid"
            " duplicates."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search terms",
                },
                "k": {
                    "type": "integer",
                    "description": "Max hits to return (default: 10)",
                    "default": 10,
                },
            },
            "required": ["query"],
        },
        handler=_search_adapter,
    ),
    Tool(
        name="wiki_get",
        description=("Fetch a single wiki page by slug (full frontmatter + body)."),
        input_schema={
            "type": "object",
            "properties": {
                "slug": {
                    "type": "string",
                    "description": "The page slug to fetch",
                },
            },
            "required": ["slug"],
        },
        handler=_get_adapter,
    ),
    Tool(
        name="wiki_lint",
        description=(
            "Run lint checks on the wiki and retrieve violations + schema-refinement suggestions"
        ),
        input_schema={
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
        handler=_lint_adapter,
    ),
)

TOOL_REGISTRY: dict[str, Tool] = {t.name: t for t in TOOLS}


def wiki_mcp_tools() -> list[dict[str, Any]]:
    """Return MCP tool definitions derived from the tool registry."""
    return [
        {
            "name": t.name,
            "description": t.description,
            "inputSchema": t.input_schema,
        }
        for t in TOOLS
    ]
