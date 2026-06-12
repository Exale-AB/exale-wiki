"""Tests for wiki HTML rendering."""

from pathlib import Path

from wiki_engine import Page, WikiRepo
from wiki_engine.render import render_wiki_to_html


def _recording_committer():
    calls: list[tuple[Path, str]] = []

    def committer(root: Path, message: str) -> None:
        calls.append((root, message))

    return committer, calls


def _repo(tmp_path: Path) -> WikiRepo:
    committer, _ = _recording_committer()
    return WikiRepo.init(tmp_path, committer=committer)


def test_render_index_html_from_catalog(tmp_path: Path):
    """Index page lists all pages grouped by category."""
    repo = _repo(tmp_path)

    # Add two pages in different categories
    page1 = Page(
        slug="gmail-setup",
        frontmatter={"title": "Gmail Setup", "category": "setup"},
        body="How to configure Gmail.",
    )
    repo.write_page(page1)

    page2 = Page(
        slug="crm-tips",
        frontmatter={"title": "CRM Tips", "category": "crm"},
        body="Best practices for CRM.",
    )
    repo.write_page(page2)

    # Update the catalog/index to include these pages
    index_content = """# Index

## setup
- [[Gmail Setup]] (gmail-setup) — How to configure Gmail.

## crm
- [[CRM Tips]] (crm-tips) — Best practices for CRM.
"""
    repo.write_index(index_content)

    # Render
    output_dir = tmp_path / "static"
    render_wiki_to_html(repo, output_dir)

    # Verify index.html exists and contains both pages
    index_html = output_dir / "index.html"
    assert index_html.exists()
    content = index_html.read_text()
    assert "Gmail Setup" in content
    assert "CRM Tips" in content
    assert "setup" in content.lower()
    assert "crm" in content.lower()
    # HTML structure assertions
    assert "<html>" in content
    assert "</html>" in content
    assert "<head>" in content
    assert "</head>" in content
    assert "<body>" in content
    assert "</body>" in content
    assert "<ul>" in content
    assert "</ul>" in content


def test_render_empty_wiki_index(tmp_path: Path):
    """Empty wiki renders valid index with no pages listed."""
    repo = _repo(tmp_path)

    # Initialize repo with empty index
    empty_index = """# Index
"""
    repo.write_index(empty_index)

    # Render
    output_dir = tmp_path / "static"
    render_wiki_to_html(repo, output_dir)

    # Verify index.html exists and has valid structure
    index_html = output_dir / "index.html"
    assert index_html.exists()
    content = index_html.read_text()
    assert "<html>" in content
    assert "</html>" in content
    assert "<head>" in content
    assert "</head>" in content
    assert "<body>" in content
    assert "</body>" in content
    assert "<h1>Knowledge Wiki</h1>" in content
    # Should not have any list items since wiki is empty
    assert "<li>" not in content


def test_render_per_page_html_with_body_and_metadata(tmp_path: Path):
    """Each page renders to a separate HTML file with frontmatter as metadata."""
    repo = _repo(tmp_path)

    page = Page(
        slug="gmail-setup",
        frontmatter={"title": "Gmail Setup", "category": "setup", "updated": "2026-06-05"},
        body="# Gmail Setup\n\nConfigure IMAP settings.",
    )
    repo.write_page(page)

    # Update the catalog/index to include this page
    index_content = """# Index

## setup
- [[Gmail Setup]] (gmail-setup) — Configure IMAP settings.
"""
    repo.write_index(index_content)

    # Render
    output_dir = tmp_path / "static"
    render_wiki_to_html(repo, output_dir)

    # Verify per-page HTML exists
    page_html = output_dir / "gmail-setup.html"
    assert page_html.exists()
    content = page_html.read_text()
    assert "Gmail Setup" in content
    assert "Configure IMAP settings" in content
    assert "2026-06-05" in content


def test_wiki_mcp_tools_have_required_fields():
    """MCP tools have name, description, and input_schema."""
    from wiki_engine.mcp_server import wiki_mcp_tools

    tools = wiki_mcp_tools()

    assert len(tools) == 6
    names = [tool["name"] for tool in tools]
    assert "wiki_query" in names
    assert "wiki_ingest" in names
    assert "wiki_context" in names
    assert "wiki_search" in names
    assert "wiki_get" in names
    assert "wiki_lint" in names

    for tool in tools:
        assert "name" in tool
        assert "description" in tool
        assert "inputSchema" in tool
        assert tool["inputSchema"]["type"] == "object"
        assert "properties" in tool["inputSchema"]


def test_wiki_query_tool_schema():
    """wiki_query tool accepts a query string."""
    from wiki_engine.mcp_server import wiki_mcp_tools

    tools = wiki_mcp_tools()
    wiki_query_tool = next(t for t in tools if t["name"] == "wiki_query")

    assert "query" in wiki_query_tool["inputSchema"]["properties"]
    assert wiki_query_tool["inputSchema"]["properties"]["query"]["type"] == "string"


def test_wiki_ingest_tool_schema():
    """wiki_ingest tool accepts source text, URL, or file identifier."""
    from wiki_engine.mcp_server import wiki_mcp_tools

    tools = wiki_mcp_tools()
    wiki_ingest_tool = next(t for t in tools if t["name"] == "wiki_ingest")

    schema = wiki_ingest_tool["inputSchema"]["properties"]
    assert "source_text" in schema or "source_url" in schema


def test_handle_wiki_query_returns_answer_with_citations(tmp_path: Path):
    """wiki_query handler executes query and returns formatted answer."""
    from wiki_engine import FakeAnswerer, FakeEmbedder, InMemoryVectorStore
    from wiki_engine.mcp_server import handle_wiki_query

    repo = _repo(tmp_path)

    page = Page(
        slug="gmail-setup",
        frontmatter={"title": "Gmail Setup", "category": "setup"},
        body="Use IMAP on port 993 for Gmail.",
    )
    repo.write_page(page)

    vectorstore = InMemoryVectorStore()
    embedder = FakeEmbedder()
    answerer = FakeAnswerer()

    result = handle_wiki_query(
        repo=repo,
        query="How do I set up Gmail?",
        file_as_new_page=False,
        vectorstore=vectorstore,
        embedder=embedder,
        answerer=answerer,
    )

    assert "answer" in result
    assert "citations" in result
    assert isinstance(result["citations"], list)


def test_handle_wiki_ingest_creates_page(tmp_path: Path):
    """wiki_ingest handler ingests source text and returns result."""
    from wiki_engine.mcp_server import handle_wiki_ingest

    repo = _repo(tmp_path)

    result = handle_wiki_ingest(
        repo=repo,
        source_text="Email from customer about billing issue",
        source_url=None,
        category="support",
        schema=None,
    )

    assert "slug" in result
    assert "title" in result
    assert "sources_merged" in result
    assert result["sources_merged"] >= 1


def test_handle_wiki_lint_returns_violations_and_suggestions(tmp_path: Path):
    """wiki_lint handler runs lint and returns violations + suggestions."""
    from wiki_engine.mcp_server import handle_wiki_lint

    repo = _repo(tmp_path)

    page = Page(
        slug="orphan",
        frontmatter={"title": "Orphan"},
        body="Unreferenced.",
    )
    repo.write_page(page)

    result = handle_wiki_lint(repo=repo, confidence_threshold=0.5, schema=None)

    assert "violations" in result
    assert "suggestions" in result
    assert isinstance(result["violations"], list)
    assert isinstance(result["suggestions"], list)
