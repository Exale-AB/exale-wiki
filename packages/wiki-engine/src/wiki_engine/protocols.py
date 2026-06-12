"""Injected intelligence seams.

The wiki engine owns the deterministic bookkeeping; the judgment steps are these
protocols, swapped for real LLM/embedding providers at runtime and for
deterministic fakes in tests (see ``fakes.py``). ``Judge`` arrives in P4c.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from .source import Source

__all__ = ["Answerer", "Embedder", "Summarizer", "Vector"]

# A single embedding vector. Plain floats keep the core dependency-free; the
# pgvector store converts to/from its own wire format at the boundary.
Vector = Sequence[float]


class Summarizer(Protocol):
    def summarize(self, source: Source) -> str: ...


class Embedder(Protocol):
    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class Answerer(Protocol):
    """Return raw context for the calling agent to synthesize from.

    The wiki is a knowledge base, not a synthesizer. The agent (Hermes) is
    responsible for the final natural-language response. This protocol formats
    retrieved context so the agent can read and synthesize it.
    """

    def answer(self, question: str, context: Sequence[str]) -> str | None:
        """Return the raw context for the agent to synthesize from.

        Args:
            question: The user's query
            context: List of retrieved page content

        Returns:
            Raw context formatted for agent consumption, or None if no context
        """
        ...
