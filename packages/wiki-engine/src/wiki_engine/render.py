"""Render the git-versioned wiki to lightweight private HTML."""

from __future__ import annotations

import html
from pathlib import Path

from .catalog import CatalogEntry, parse_index
from .repo import WikiRepo

__all__ = ["render_wiki_to_html"]


def _render_html(entries_by_category: dict[str, list[CatalogEntry]]) -> str:
    """Render index.html from catalog entries grouped by category."""
    css = (
        "body { font-family: -apple-system, BlinkMacSystemFont, "
        '"Segoe UI", sans-serif; max-width: 900px; margin: 0 auto; '
        "padding: 2rem; } h1 { color: #333; } h2 { color: #666; "
        "margin-top: 2rem; border-bottom: 1px solid #ddd; "
        "padding-bottom: 0.5rem; } ul { list-style: none; padding: 0; } "
        "li { padding: 0.5rem 0; } a { color: #0066cc; "
        "text-decoration: none; } a:hover { text-decoration: underline; }"
    )

    lines = [
        "<!DOCTYPE html>",
        "<html>",
        "<head>",
        '  <meta charset="UTF-8">',
        '  <meta name="viewport" content="width=device-width, initial-scale=1.0">',
        "  <title>Knowledge Wiki</title>",
        "  <style>",
        f"    {css}",
        "  </style>",
        "</head>",
        "<body>",
        "<h1>Knowledge Wiki</h1>",
    ]

    for category in sorted(entries_by_category.keys()):
        lines.append(f"  <h2>{html.escape(category)}</h2>")
        lines.append("  <ul>")
        for entry in entries_by_category[category]:
            escaped_slug = html.escape(entry.slug)
            escaped_title = html.escape(entry.title)
            lines.append(f'    <li><a href="{escaped_slug}.html">{escaped_title}</a></li>')
        lines.append("  </ul>")

    lines.extend(["</body>", "</html>"])
    return "\n".join(lines)


def _render_page_html(title: str, category: str, updated: str | None, body: str) -> str:
    """Render a single page HTML from metadata and body."""
    title_escaped = html.escape(title)
    category_escaped = html.escape(category)

    metadata = f"    <p><strong>Category:</strong> {category_escaped}</p>\n"
    if updated:
        updated_escaped = html.escape(updated)
        metadata += f"    <p><strong>Updated:</strong> {updated_escaped}</p>\n"

    return f"""<html>
<head><title>{title_escaped}</title></head>
<body>
<h1>{title_escaped}</h1>
<div class="metadata">
{metadata}</div>
<div class="body">{body}</div>
</body>
</html>"""


def render_wiki_to_html(repo: WikiRepo, output_dir: Path) -> None:
    """Render all wiki pages to static HTML.

    Reads pages from repo.wiki_path, renders to output_dir/index.html
    and per-page HTML files. Creates output_dir if it doesn't exist.

    Args:
        repo: WikiRepo instance.
        output_dir: Path where HTML files will be written.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Read catalog to get all pages grouped by category
    index_text = repo.read_index()
    entries = parse_index(index_text)

    # Group entries by category
    entries_by_category: dict[str, list[CatalogEntry]] = {}
    for entry in entries:
        cat = entry.category
        entries_by_category.setdefault(cat, []).append(entry)

    # Render index.html
    html_content = _render_html(entries_by_category)
    index_html = output_dir / "index.html"
    index_html.write_text(html_content, encoding="utf-8")

    # Render per-page HTML files
    for slug in [entry.slug for entries in entries_by_category.values() for entry in entries]:
        page = repo.read_page(slug)
        if page:
            title = str(page.frontmatter.get("title", slug))
            category = str(page.frontmatter.get("category", "uncategorized"))
            updated = page.frontmatter.get("updated")
            updated_str = str(updated) if updated else None

            page_html_content = _render_page_html(title, category, updated_str, page.body)
            page_html = output_dir / f"{slug}.html"
            page_html.write_text(page_html_content, encoding="utf-8")
