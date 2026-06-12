"""Deterministic fakes for the injected protocols (tests/dev, no network)."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

from .protocols import ExtractedFacts
from .source import Source

__all__ = [
    "FakeAnswerer",
    "FakeConflictResolver",
    "FakeEmbedder",
    "FakeFactExtractor",
    "FakeSummarizer",
]

_MAX_SNIPPET = 200
_ANSWER_MAX = 500


class FakeSummarizer:
    """Stand-in for an LLM summarizer: title + the source's first line."""

    def summarize(self, source: Source) -> str:
        first_line = source.text.strip().splitlines()[0] if source.text.strip() else ""
        snippet = first_line[:_MAX_SNIPPET]
        return f"Summary of {source.title}: {snippet}".rstrip()


class FakeEmbedder:
    """Deterministic hashed bag-of-words embedding (no model, no network).

    Each lowercased token is hashed into one of ``dim`` buckets and increments
    that coordinate, so texts that share words get similar vectors and cosine
    similarity is meaningful for retrieval-ranking tests.
    """

    def __init__(self, dim: int = 16) -> None:
        self.dim = dim

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        for token in text.lower().split():
            bucket = int(hashlib.sha256(token.encode()).hexdigest(), 16) % self.dim
            vector[bucket] += 1.0
        return vector


class FakeFactExtractor:
    """No-op extractor: returns empty entities and facts (no spaCy/LLM needed)."""

    def extract(self, text: str) -> ExtractedFacts:
        return ExtractedFacts(entities=(), facts=())


class FakeConflictResolver:
    """No-op resolver: returns keep_both for every conflict (no LLM needed)."""

    def resolve(self, conflicts: list, repo: object = None) -> list:
        from .conflicts import Resolution

        return [
            Resolution(
                conflict=c,
                action="keep_both",
                resolved_fact=None,
                reason="fake resolver",
            )
            for c in conflicts
        ]


class FakeAnswerer:
    """Return raw context formatted for the agent to synthesize from.

    The agent (Hermes) is responsible for the final natural-language response.
    This fake implementation just formats the retrieved context with separators.
    """

    def answer(self, question: str, context: Sequence[str]) -> str | None:
        """Return the raw context for the agent to synthesize from.

        Args:
            question: The user's query
            context: List of retrieved page content

        Returns:
            Raw context formatted with separators, prefixed with the question
        """
        if not context:
            return f"Question: {question}\n\nNo relevant pages found."

        # Filter empty contexts
        valid_content = [c for c in context if c and c.strip()]
        if not valid_content:
            return f"Question: {question}\n\nNo relevant pages found."

        # Return raw context with separators
        return f"Question: {question}\n\n" + "\n\n---\n\n".join(valid_content)
