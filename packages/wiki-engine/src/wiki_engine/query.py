"""The query operation: retrieve -> format raw context -> (optionally) file.

The wiki returns RAW context, not synthesized answers. The calling agent (Hermes)
is responsible for reading the context and synthesizing the final response.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from . import catalog
from .log import LogEntry, today
from .page import Page
from .protocols import Answerer
from .repo import WikiRepo
from .slug import slugify

__all__ = ["Answer", "Retrieves", "query"]


class Retrieves(Protocol):
    """Anything that can retrieve relevant page slugs for a question.

    The concrete ``retrieval.Retriever`` satisfies this, but so does any
    deterministic stand-in injected in tests — the engine depends on the
    behaviour, not the class.
    """

    def retrieve(self, question: str, *, k: int = 5) -> list[str]: ...


_SUMMARY_LINE_MAX = 120
_FILED_CATEGORY = "Answers"


@dataclass(frozen=True)
class Answer:
    """Query result containing raw context for agent synthesis.

    Attributes:
        text: Raw context formatted for the agent, or None if no context found
        citations: Tuple of page slugs that were retrieved
        filed_slug: Optional slug if the answer was filed as a new page
    """

    text: str | None
    citations: tuple[str, ...]
    filed_slug: str | None = None


def query(
    question: str,
    *,
    retriever: Retrieves,
    answerer: Answerer,
    repo: WikiRepo,
    k: int = 5,
    file_as: str | None = None,
    date: str | None = None,
) -> Answer:
    """Query the wiki and return raw context for the agent to synthesize from.

    The wiki is a knowledge base, not a synthesizer. This function retrieves
    relevant pages and formats them as raw context. The calling agent (Hermes)
    is responsible for reading the context and generating the final response.

    Args:
        question: The user's query
        retriever: Retriever for finding relevant pages
        answerer: Answerer for formatting raw context
        repo: Wiki repository
        k: Number of pages to retrieve (default: 5)
        file_as: Optional title to file the answer as a new page
        date: Optional date for the log entry (defaults to today)

    Returns:
        Answer with raw context text, citations, and optional filed_slug
    """
    slugs = retriever.retrieve(question, k=k)
    found = [(slug, page) for slug in slugs if (page := repo.read_page(slug)) is not None]
    context = [page.body for _, page in found]
    citations = tuple(slug for slug, _ in found)
    text = answerer.answer(question, context)

    filed_slug = None
    if file_as is not None and text is not None:
        filed_slug = _file_answer(repo, file_as, text, citations, date or today())

    return Answer(text=text, citations=citations, filed_slug=filed_slug)


def _file_answer(
    repo: WikiRepo, title: str, text: str, citations: tuple[str, ...], date: str
) -> str:
    slug = slugify(title)
    with repo.transaction(f"query: {title}") as txn:
        txn.put_page(
            Page(
                slug=slug,
                frontmatter={"title": title, "type": "answer", "citations": list(citations)},
                body=text,
            )
        )
        txn.catalog(
            catalog.CatalogEntry(
                title=title,
                slug=slug,
                category=_FILED_CATEGORY,
                summary=(text.splitlines() or [""])[0][:_SUMMARY_LINE_MAX],
            )
        )
        txn.log(LogEntry(date=date, op="query", title=title))
    return slug
