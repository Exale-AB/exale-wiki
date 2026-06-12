"""The wiki Page: YAML frontmatter + markdown body + [[wikilinks]]."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import yaml

from .errors import WikiError

__all__ = ["Page", "extract_wikilinks", "parse_page", "render_page"]

_WIKILINK = re.compile(r"\[\[([^\[\]]+)\]\]")
_FRONTMATTER = re.compile(r"^---\n(.*?)\n---\n?(.*)$", re.DOTALL)


def extract_wikilinks(body: str) -> tuple[str, ...]:
    return tuple(match.group(1).strip() for match in _WIKILINK.finditer(body))


@dataclass(frozen=True)
class Page:
    slug: str
    frontmatter: Mapping[str, Any]
    body: str

    @property
    def title(self) -> str:
        return str(self.frontmatter.get("title", self.slug))

    @property
    def wikilinks(self) -> tuple[str, ...]:
        return extract_wikilinks(self.body)


def parse_page(slug: str, text: str) -> Page:
    match = _FRONTMATTER.match(text)
    if match:
        raw, body = match.group(1), match.group(2)
        try:
            frontmatter = yaml.safe_load(raw) or {}
        except yaml.YAMLError as exc:
            raise WikiError(f"invalid page frontmatter: {exc}") from exc
        if not isinstance(frontmatter, dict):
            raise WikiError("page frontmatter must be a mapping")
    else:
        frontmatter, body = {}, text
    return Page(slug=slug, frontmatter=frontmatter, body=body.strip() + "\n")


def render_page(page: Page) -> str:
    body = page.body.strip()
    if page.frontmatter:
        front = yaml.safe_dump(dict(page.frontmatter), sort_keys=True, allow_unicode=True).strip()
        return f"---\n{front}\n---\n\n{body}\n"
    return f"{body}\n"
