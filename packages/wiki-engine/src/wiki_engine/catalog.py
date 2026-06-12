"""The index.md content catalog: one line per page, grouped by category."""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = ["CatalogEntry", "parse_index", "render_index", "upsert_entry"]

_LINE = re.compile(r"^- \[\[(?P<title>[^\]]+)\]\] \((?P<slug>[^)]+)\) — (?P<summary>.*)$")


@dataclass(frozen=True)
class CatalogEntry:
    title: str
    slug: str
    category: str
    summary: str


def parse_index(text: str) -> list[CatalogEntry]:
    entries: list[CatalogEntry] = []
    category = "General"
    for line in text.splitlines():
        if line.startswith("## "):
            category = line[3:].strip()
            continue
        match = _LINE.match(line)
        if match:
            entries.append(
                CatalogEntry(
                    title=match["title"],
                    slug=match["slug"],
                    category=category,
                    summary=match["summary"],
                )
            )
    return entries


def render_index(entries: list[CatalogEntry]) -> str:
    by_category: dict[str, list[CatalogEntry]] = {}
    for entry in entries:
        by_category.setdefault(entry.category, []).append(entry)

    lines = ["# Index", ""]
    for category in sorted(by_category):
        lines.append(f"## {category}")
        for entry in sorted(by_category[category], key=lambda e: e.slug):
            lines.append(f"- [[{entry.title}]] ({entry.slug}) — {entry.summary}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def upsert_entry(entries: list[CatalogEntry], entry: CatalogEntry) -> list[CatalogEntry]:
    kept = [e for e in entries if e.slug != entry.slug]
    kept.append(entry)
    return kept
