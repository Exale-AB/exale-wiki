"""Split page bodies into coherent chunks for token-budgeted retrieval (T08).

Markdown is chunked by heading first, then packed by paragraph to stay under a
char budget (≈ tokens × 4). Each chunk carries its parent slug + heading so
citations still resolve to whole pages while retrieval ranks at chunk granularity.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = ["Chunk", "chunk_page"]

_HEADING = re.compile(r"^#{1,6}\s+\S")
_CHARS_PER_TOKEN = 4
_DEFAULT_MAX_TOKENS = 256


@dataclass(frozen=True)
class Chunk:
    slug: str
    heading: str
    text: str


def _sections(body: str) -> list[tuple[str, str]]:
    """Split into (heading, text) sections at markdown heading lines."""
    sections: list[tuple[str, list[str]]] = [("", [])]
    for line in body.splitlines():
        if _HEADING.match(line):
            sections.append((line.strip(), []))
        else:
            sections[-1][1].append(line)
    return [(h, "\n".join(lines)) for h, lines in sections]


def _pack_paragraphs(text: str, max_chars: int) -> list[str]:
    """Pack blank-line-separated paragraphs into pieces under ``max_chars``."""
    pieces: list[str] = []
    current = ""
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if not para:
            continue
        if len(para) > max_chars:  # a single oversized paragraph: hard-split it
            if current:
                pieces.append(current)
                current = ""
            for i in range(0, len(para), max_chars):
                pieces.append(para[i : i + max_chars])
            continue
        candidate = f"{current}\n\n{para}" if current else para
        if len(candidate) > max_chars:
            pieces.append(current)
            current = para
        else:
            current = candidate
    if current:
        pieces.append(current)
    return pieces


def chunk_page(slug: str, body: str, *, max_tokens: int = _DEFAULT_MAX_TOKENS) -> list[Chunk]:
    """Chunk a page body into heading-scoped, budget-bounded pieces."""
    max_chars = max(1, max_tokens) * _CHARS_PER_TOKEN
    chunks: list[Chunk] = []
    for heading, text in _sections(body):
        text = text.strip()
        if not text:
            continue
        if len(text) <= max_chars:
            chunks.append(Chunk(slug, heading, text))
        else:
            chunks.extend(
                Chunk(slug, heading, piece) for piece in _pack_paragraphs(text, max_chars)
            )
    return chunks
