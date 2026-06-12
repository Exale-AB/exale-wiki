from pathlib import Path

from wiki_engine.catalog import parse_index
from wiki_engine.fakes import FakeAnswerer, FakeEmbedder
from wiki_engine.log import parse_log
from wiki_engine.page import Page
from wiki_engine.query import Answer, query
from wiki_engine.repo import WikiRepo
from wiki_engine.retrieval import InMemoryVectorStore, Retriever


def _repo(tmp_path: Path) -> WikiRepo:
    return WikiRepo.init(tmp_path, committer=lambda _r, _m: None)


def _retriever(repo: WikiRepo) -> Retriever:
    return Retriever(repo=repo, store=InMemoryVectorStore(), embedder=FakeEmbedder())


def _seed(repo: WikiRepo) -> None:
    repo.write_page(
        Page(slug="acme-ab", frontmatter={"title": "Acme AB"}, body="Renewal due 2026-06-20.")
    )
    repo.write_index(
        "# Index\n\n## Accounts\n- [[Acme AB]] (acme-ab) — renewal contract overview\n"
    )


def test_query_returns_raw_context_with_citations(tmp_path: Path):
    """Test that query returns raw context formatted for agent synthesis."""
    repo = _repo(tmp_path)
    _seed(repo)
    result = query(
        "renewal contract", retriever=_retriever(repo), answerer=FakeAnswerer(), repo=repo
    )
    assert isinstance(result, Answer)
    assert result.citations == ("acme-ab",)
    # Raw context should contain the question and the page body
    assert result.text is not None
    assert "Question: renewal contract" in result.text
    assert "Renewal due 2026-06-20." in result.text
    assert result.filed_slug is None


def test_query_with_no_hits_returns_empty_citations(tmp_path: Path):
    repo = _repo(tmp_path)
    repo.write_index("# Index\n")
    result = query("kubernetes", retriever=_retriever(repo), answerer=FakeAnswerer(), repo=repo)
    assert result.citations == ()
    assert isinstance(result.text, str)


def test_query_files_answer_as_page_when_requested(tmp_path: Path):
    repo = _repo(tmp_path)
    _seed(repo)
    commits: list[str] = []
    repo._committer = lambda _root, msg: commits.append(msg)  # capture commit

    result = query(
        "When is the Acme renewal?",
        retriever=_retriever(repo),
        answerer=FakeAnswerer(),
        repo=repo,
        file_as="Acme Renewal Date",
        date="2026-06-04",
    )

    assert result.filed_slug == "acme-renewal-date"
    page = repo.read_page("acme-renewal-date")
    assert page is not None
    assert page.frontmatter["type"] == "answer"
    assert page.frontmatter["citations"] == ["acme-ab"]
    assert result.text is not None
    assert result.text in page.body

    assert "(acme-renewal-date)" in repo.read_index()
    log = parse_log(repo.read_log())
    assert log[-1].op == "query" and log[-1].title == "Acme Renewal Date"
    assert commits == ["query: Acme Renewal Date"]


def test_query_does_not_file_by_default(tmp_path: Path):
    repo = _repo(tmp_path)
    _seed(repo)
    query("renewal", retriever=_retriever(repo), answerer=FakeAnswerer(), repo=repo)
    assert parse_index(repo.read_index()) == [
        # only the seeded entry remains; no answer page filed
        type(parse_index(repo.read_index())[0])(
            title="Acme AB",
            slug="acme-ab",
            category="Accounts",
            summary="renewal contract overview",
        )
    ]


def test_query_returns_raw_context_for_agent(tmp_path: Path):
    """Test that query returns raw context with proper formatting for agent synthesis.

    The wiki is a knowledge base, not a synthesizer. It should return raw page
    content with separators so the calling agent (Hermes) can synthesize the
    final response.
    """
    repo = _repo(tmp_path)

    # Create multiple pages with real content that has word overlap with the query
    # (FakeEmbedder uses bag-of-words hashing, so we need shared words)
    repo.write_page(
        Page(
            slug="gmail-setup",
            frontmatter={"title": "Gmail Setup"},
            body=(
                "Gmail setup instructions:\n"
                "1. Go to gmail.com\n"
                "2. Click Sign In\n"
                "3. Enter credentials\n"
                "Gmail is a free email service."
            ),
        )
    )
    repo.write_page(
        Page(
            slug="email-best-practices",
            frontmatter={"title": "Email Best Practices"},
            body=(
                "Email best practices:\n"
                "- Use clear subject lines\n"
                "- Keep email messages concise\n"
                "- Reply to email promptly"
            ),
        )
    )
    repo.write_index(
        "# Index\n\n"
        "## Email\n"
        "- [[Gmail Setup]] (gmail-setup) — gmail setup email instructions\n"
        "- [[Email Best Practices]] (email-best-practices) — email best practices\n"
    )

    result = query(
        "gmail email setup",  # Query with shared words
        retriever=_retriever(repo),
        answerer=FakeAnswerer(),
        repo=repo,
    )

    # Should return raw context, not synthesized prose
    assert result.text is not None
    assert "Question: gmail email setup" in result.text

    # Should contain full page bodies (not summaries)
    assert "Gmail setup instructions:" in result.text or "Email best practices:" in result.text

    # Should use separators if multiple pages found
    if len(result.citations) > 1:
        assert "---" in result.text

    # Should have citations
    assert len(result.citations) >= 1
    assert result.citations[0] in ("gmail-setup", "email-best-practices")


def test_query_handles_empty_context(tmp_path: Path):
    """Test that query returns 'No relevant pages found' when all context is empty."""
    repo = _repo(tmp_path)

    class EmptyRetriever:
        def retrieve(self, question: str, k: int = 5):
            return []

    result = query(
        "test question",
        retriever=EmptyRetriever(),
        answerer=FakeAnswerer(),
        repo=repo,
    )

    assert result.text is not None
    assert "No relevant pages found" in result.text
    assert result.citations == ()


def test_answerer_filters_whitespace_only_context(tmp_path: Path):
    """Test that answerer filters out whitespace-only context."""
    from wiki_engine.fakes import FakeAnswerer

    answerer = FakeAnswerer()
    result = answerer.answer("test", ["   ", "  \n  ", ""])

    assert result is not None
    assert "No relevant pages found" in result
