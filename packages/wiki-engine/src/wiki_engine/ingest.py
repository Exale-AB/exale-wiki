"""The ingest operation: source -> page (summary, or verbatim for documents) + index/log updates.

Idempotent (dedup by source identity) and off-limits-aware. The single judgment
step (summarize) is injected; everything else is deterministic bookkeeping.
Sources whose category is in ``schema.verbatim_categories`` (default ``document``)
are stored in full instead of summarized, so dense documents like CVs stay matchable.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass

from . import catalog
from .errors import IngestError
from .log import LogEntry, today
from .page import Page
from .protocols import Embedder, FactExtractor, Summarizer
from .records import merge_records
from .repo import WikiRepo
from .retrieval import VectorStore
from .schema import WikiSchema
from .sections import upsert_section
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
    extractor: FactExtractor | None = None,
    graph: object | None = None,
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

    # Verbatim categories (e.g. "document") are stored in full so dense sources
    # like CVs stay matchable — the summary would drop skills/certs/experience.
    # Everything else gets the injected summary. The page category equals
    # ``schema.default_category`` (set per-ingest by the caller), so that is what
    # decides verbatim storage.
    verbatim = schema.default_category in schema.verbatim_categories
    body = source.text if verbatim else summarizer.summarize(source)
    embedding = embedder.embed([body])[0] if embedder is not None and store is not None else None
    extracted = extractor.extract(body) if extractor is not None else None

    # Serialize the dedup check + filesystem/git writes so concurrent ingests from
    # multiple workflows don't race on the manifest/index/log or the git index. The
    # model calls above are deliberately kept outside the lock.
    with repo.transaction(f"ingest: {source.title}") as txn:
        if source.identity() in _manifest_ids(repo):
            txn.abort()
            return IngestResult(slug=None, skipped=True)

        (repo.raw_dir / f"{source.identity()}.txt").write_text(source.text, encoding="utf-8")
        _append_manifest(repo, source, date)

        existing = repo.read_page(slug)
        sources = _merge_sources(existing, source.identifier)
        frontmatter: dict[str, object] = {
            "title": source.title,
            "type": "source",
            "category": schema.default_category,
            "sources": sources,
        }
        if contributor:
            frontmatter["contributor"] = contributor

        # Accumulate rather than replace. The body used to be the newest source's
        # summary alone, so a page claiming two sources contained only one of
        # them (#21) — on every re-ingest, not just a failed one.
        page_body = upsert_section(
            existing.body if existing else "",
            identifier=source.identifier,
            date=date,
            text=body,
        )

        if extracted is not None:
            # Records written before attribution existed belong to whichever
            # source the page cited first.
            first_source = sources[0] if sources else None
            entities = merge_records(
                list(existing.frontmatter.get("entities", [])) if existing else [],
                [{"text": e.text, "entity_type": e.entity_type} for e in extracted.entities],
                source=source.identifier,
                first_source=first_source,
                extraction_failed=extracted.relations_failed,
            )
            facts = merge_records(
                list(existing.frontmatter.get("facts", [])) if existing else [],
                [
                    {
                        "head": f.head,
                        "relation": f.relation,
                        "tail": f.tail,
                        "head_type": f.head_type,
                        "tail_type": f.tail_type,
                    }
                    for f in extracted.facts
                ],
                source=source.identifier,
                first_source=first_source,
                extraction_failed=extracted.relations_failed,
            )
            if entities:
                frontmatter["entities"] = entities
            if facts:
                frontmatter["facts"] = facts

        page = Page(slug=slug, frontmatter=frontmatter, body=page_body)
        schema.enforce_page(page)
        txn.put_page(page)

        if store is not None and embedding is not None:
            store.upsert(slug, embedding)

        if graph is not None and extracted is not None:
            graph.update(slug, extracted)  # type: ignore[union-attr]

        txn.catalog(
            catalog.CatalogEntry(
                title=source.title,
                slug=slug,
                category=schema.default_category,
                summary=(body.splitlines() or [""])[0][:_SUMMARY_LINE_MAX],
            )
        )
        txn.log(LogEntry(date=date, op="ingest", title=source.title))

        return IngestResult(slug=slug, created=existing is None, updated=existing is not None)
