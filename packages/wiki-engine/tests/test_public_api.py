import wiki_engine as we


def test_public_api_surface():
    expected = {
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
        "Retrieved",
        "Retriever",
        "Source",
        "SourceKind",
        "Summarizer",
        "VectorStore",
        "WikiError",
        "WikiRepo",
        "WikiSchema",
        "ingest",
        "parse_schema",
        "query",
        "slugify",
    }
    assert expected.issubset(set(we.__all__))
    for name in expected:
        assert hasattr(we, name), name


def test_render_and_mcp_functions_exported():
    """render_wiki_to_html and mcp tool functions are in public API."""
    assert hasattr(we, "render_wiki_to_html")
    assert hasattr(we, "wiki_mcp_tools")
    assert hasattr(we, "handle_wiki_query")
    assert hasattr(we, "handle_wiki_ingest")
    assert hasattr(we, "handle_wiki_lint")
