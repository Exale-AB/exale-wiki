"""The ingest operation: source -> summary page + index/log updates.

Idempotent (dedup by source identity) and off-limits-aware. The single judgment
step (summarize) is injected; everything else is deterministic bookkeeping.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass

from . import catalog
from .errors import IngestError
from .log import LogEntry, format_entry, today
from .page import Page
from .protocols import Embedder, Summarizer
from .repo import WikiRepo
from .retrieval import VectorStore
from .schema import WikiSchema
from .slug import slugify
from .source import Source

__all__ = ["IngestResult", "ingest"]

_MANIFEST = "manifest.jsonl"
_SUMMARY_LINE_MAX = 120


@dataclass(frozen=True)
class IngestResult:
    slug: str | None
    created: bool = False
    updated: bool = False
    skipped: bool = False
    excluded: bool = False


def _manifest_ids(repo: WikiRepo) -> set[str]:
    path = repo.raw_dir / _MANIFEST
    if not path.exists():
        return set()
    return {
        json.loads(line)["id"]
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }


def _append_manifest(repo: WikiRepo, source: Source, date: str) -> None:
    record = {
        "id": source.identity(),
        "kind": str(source.kind),
        "identifier": source.identifier,
        "title": source.title,
        "date": date,
    }
    path = repo.raw_dir / _MANIFEST
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _merge_sources(existing: Page | None, identifier: str) -> list[str]:
    prior = list(existing.frontmatter.get("sources", [])) if existing else []
    if identifier in prior:
        return prior
    return [*prior, identifier]


def ingest(
    source: Source,
    *,
    repo: WikiRepo,
    schema: WikiSchema,
    summarizer: Summarizer,
    off_limits: Iterable[str] = (),
    date: str | None = None,
    embedder: Embedder | None = None,
    store: VectorStore | None = None,
    contributor: str | None = None,
) -> IngestResult:
    date = date or today()

    # Enforce schema rules before proceeding with ingest
    schema.enforce_source(source)

    if set(source.categories) & set(off_limits):
        return IngestResult(slug=None, excluded=True)

    # Optimistic dedup check before the (costly) summarize. The authoritative re-check
    # happens inside the write lock below to stay race-safe under concurrency.
    if source.identity() in _manifest_ids(repo):
        return IngestResult(slug=None, skipped=True)

    slug = slugify(source.title)
    if not slug:
        raise IngestError(f"source title produces an empty slug: {source.title!r}")

    summary = summarizer.summarize(source)
    embedding = embedder.embed([summary])[0] if embedder is not None and store is not None else None

    # Serialize the dedup check + filesystem/git writes so concurrent ingests from
    # multiple workflows don't race on the manifest/index/log or the git index. The
    # model calls above are deliberately kept outside the lock.
    with repo.write_lock():
        if source.identity() in _manifest_ids(repo):
            return IngestResult(slug=None, skipped=True)

        (repo.raw_dir / f"{source.identity()}.txt").write_text(source.text, encoding="utf-8")
        _append_manifest(repo, source, date)

        existing = repo.read_page(slug)
        frontmatter: dict[str, object] = {
            "title": source.title,
            "type": "source",
            "category": schema.default_category,
            "sources": _merge_sources(existing, source.identifier),
        }
        if contributor:
            frontmatter["contributor"] = contributor
        page = Page(slug=slug, frontmatter=frontmatter, body=summary)
        # Enforce the full page ruleset (type/category/honesty) before persisting.
        schema.enforce_page(page)
        repo.write_page(page)

        if store is not None and embedding is not None:
            store.upsert(slug, embedding)

        entries = catalog.upsert_entry(
            catalog.parse_index(repo.read_index()),
            catalog.CatalogEntry(
                title=source.title,
                slug=slug,
                category=schema.default_category,
                summary=(summary.splitlines() or [""])[0][:_SUMMARY_LINE_MAX],
            ),
        )
        repo.write_index(catalog.render_index(entries))

        repo.append_log(format_entry(LogEntry(date=date, op="ingest", title=source.title)))
        repo.commit(f"ingest: {source.title}")

        return IngestResult(slug=slug, created=existing is None, updated=existing is not None)
