"""Per-source sections in a page body.

`ingest` used to write the newest source's summary as the *whole* body, so a page
that cited two sources contained only the second one's content — on every
re-ingest, successful or not (#21). A page now holds one section per source:

    ## 2026-03-01 — msg-1

    Summary of the first source.

    ## 2026-03-04 — msg-2

    Summary of the second source.

`chunk.py` already splits bodies on markdown headings and attaches the heading to
each chunk, so this gives retrieval per-source chunks and citations for free.

Only headings matching the section pattern are boundaries. A verbatim document
legitimately contains its own `## Terms`, and that is content, not a new source.

Pure string functions: no repo, no model, no I/O.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

__all__ = ["Section", "parse_sections", "render_sections", "upsert_section"]

_SEPARATOR: Final = " — "  # em dash, so ordinary hyphenated ids do not collide
_SECTION_HEADING: Final = re.compile(rf"^##\s+(?P<date>\S+){_SEPARATOR}(?P<identifier>.+?)\s*$")
_ISO_DATE: Final = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Identifiers arrive from external systems (message ids, file paths, URLs). One
# containing a newline could forge a section boundary and silently reattribute
# another source's content, so they are rejected rather than escaped — an
# identifier that needs escaping is a sign the caller has the wrong value.
_FORBIDDEN: Final = ("\n", "\r")


@dataclass(frozen=True)
class Section:
    """One source's contribution to a page.

    ``identifier`` is None for a body written before sections existed: it is
    adopted as the page's first section rather than being rewritten.
    """

    identifier: str | None
    date: str
    text: str


def _validate(identifier: str) -> str:
    cleaned = identifier.strip()
    if not cleaned:
        raise ValueError("source identifier is empty")
    if any(char in identifier for char in _FORBIDDEN):
        raise ValueError(f"source identifier contains a line break: {identifier!r}")
    if cleaned.startswith("#"):
        raise ValueError(f"source identifier would look like a heading: {identifier!r}")
    return cleaned


def _sort_key(section: Section) -> tuple[int, str, str]:
    """Anonymous first, then by date, with unparseable dates last.

    A malformed date must not crash a write — the page is still worth having.
    """
    if section.identifier is None:
        return (0, "", "")
    rank = 1 if _ISO_DATE.match(section.date) else 2
    return (rank, section.date, section.identifier)


def parse_sections(body: str) -> list[Section]:
    """Split ``body`` into its per-source sections.

    A body with no section headings yields a single anonymous section. An empty
    or whitespace-only body yields none.
    """
    sections: list[Section] = []
    preamble: list[str] = []
    current: tuple[str, str] | None = None
    lines: list[str] = []

    for line in body.splitlines():
        match = _SECTION_HEADING.match(line)
        if match is None:
            (lines if current is not None else preamble).append(line)
            continue
        if current is not None:
            sections.append(Section(current[1], current[0], "\n".join(lines).strip()))
        elif preamble and "\n".join(preamble).strip():
            sections.append(Section(None, "", "\n".join(preamble).strip()))
        current = (match.group("date"), match.group("identifier"))
        lines = []

    if current is not None:
        sections.append(Section(current[1], current[0], "\n".join(lines).strip()))
    elif "\n".join(preamble).strip():
        sections.append(Section(None, "", "\n".join(preamble).strip()))

    return sections


def render_sections(sections: list[Section]) -> str:
    """Render sections back to a page body, ordered deterministically."""
    blocks: list[str] = []
    for section in sorted(sections, key=_sort_key):
        if section.identifier is None:
            blocks.append(section.text.strip())
            continue
        heading = f"## {section.date}{_SEPARATOR}{section.identifier}"
        blocks.append(f"{heading}\n\n{section.text.strip()}")
    return "\n\n".join(block for block in blocks if block) + "\n"


def upsert_section(body: str, *, identifier: str, date: str, text: str) -> str:
    """Add or replace one source's section, leaving every other source's intact.

    Replacing rather than appending is what makes re-ingesting a changed source
    idempotent. An unsectioned legacy body is kept as an anonymous first section.
    """
    identifier = _validate(identifier)
    kept = [s for s in parse_sections(body) if s.identifier != identifier]
    return render_sections([*kept, Section(identifier, date, text)])
