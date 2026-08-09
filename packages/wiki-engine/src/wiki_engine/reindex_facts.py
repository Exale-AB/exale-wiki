"""Backfill CLI: extract facts for all pages and rebuild the knowledge graph.

python -m wiki_engine.reindex_facts        # process all pages
python -m wiki_engine.reindex_facts --force # re-extract even if facts exist

`--force` means re-extract from scratch, so a page whose extraction returns
nothing has its records *cleared*. It used to preserve them, because a failed
extraction and an empty one were the same empty tuple — so a page that timed out
kept its old records while still being rewritten, and the mtime claimed
otherwise. Twelve pages on one seat survived a full --force run that way.

Extraction runs **per body section**, so records stay attributed to the source
they came from; a whole-page pass would flatten the attribution `ingest`
establishes.

A page whose sections all fail is left untouched and counted in
`ReindexFactsResult.failed`. Untouched rather than cleared, because a transient
timeout must not delete real facts, and rewriting it would move the mtime for
nothing. A page where only *some* sections failed is written, with those
sections keeping their previous records, and counted in `partial`.

Note the cost asymmetry: this CLI spends tokens. If all you need is to bring
persisted types onto a changed vocabulary, `python -m wiki_engine.relabel` does
that as a pure data migration.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .knowledge_graph import WikiGraph, prune_legacy_graph
from .page import Page
from .protocols import ExtractedFacts, FactExtractor
from .records import merge_records
from .repo import WikiRepo
from .sections import parse_sections

__all__ = ["ReindexFactsResult", "reindex_facts"]


@dataclass(frozen=True)
class ReindexFactsResult:
    processed: int
    graph_vertices: int
    # Pages where *every* section's extraction failed, so the page was left
    # untouched. Reported so a run that converted less than it looks like cannot
    # pass for a complete one — see the module docstring.
    failed: int = 0
    # Pages written, but where at least one section kept its previous records
    # because that section's extraction failed. The body and those records can
    # disagree until a later run; `lint` reports it.
    partial: int = 0


def reindex_facts(
    repo: WikiRepo,
    extractor: FactExtractor,
    *,
    graph_path: Path | None = None,
    force: bool = False,
) -> ReindexFactsResult:
    """Extract facts for all pages and rebuild the graph."""
    # Default to the repo's own path. This used to be decided by the caller, and
    # the CLI chose a different file from the MCP server.
    graph = WikiGraph(path=repo.graph_path if graph_path is None else graph_path)
    processed = 0
    failed = 0
    partial = 0

    for page in repo.list_pages():
        if not force and page.frontmatter.get("facts"):
            continue

        fm = dict(page.frontmatter)
        sources = list(fm.get("sources", []))
        first_source = str(sources[0]) if sources else None
        sections = parse_sections(page.body)

        entities: list[Any] = list(fm.get("entities", []))
        facts: list[Any] = list(fm.get("facts", []))
        results: list[ExtractedFacts] = []
        failures = 0

        # Extract per section so records stay attributed to their source. A
        # whole-body pass would flatten the attribution ingest establishes.
        for section in sections:
            extracted = extractor.extract(section.text)
            results.append(extracted)
            if extracted.relations_failed:
                failures += 1
            source = section.identifier or first_source
            if source is None:
                # A page with no cited source (e.g. one filed by `query`). Nothing
                # to attribute to, so fall back to whole-page replacement.
                entities = _entity_records(extracted)
                facts = _fact_records(extracted)
                continue
            entities = merge_records(
                entities,
                _entity_records(extracted),
                source=source,
                first_source=first_source,
                extraction_failed=extracted.relations_failed,
            )
            facts = merge_records(
                facts,
                _fact_records(extracted),
                source=source,
                first_source=first_source,
                extraction_failed=extracted.relations_failed,
            )

        # Every section failed: leave the page entirely alone. Rewriting it would
        # move the mtime while the records stayed stale, which is what let a
        # --force run look complete when it was not.
        if sections and failures == len(sections):
            failed += 1
            continue
        if failures:
            partial += 1

        fm.pop("entities", None)
        fm.pop("facts", None)
        if entities:
            fm["entities"] = entities
        if facts:
            fm["facts"] = facts
        repo.write_page(Page(slug=page.slug, frontmatter=fm, body=page.body))

        for extracted in results:
            if extracted.entities or extracted.facts:
                graph.update(page.slug, extracted)
        processed += 1

    graph.save()
    return ReindexFactsResult(
        processed=processed,
        graph_vertices=graph.stats["entities"] + graph.stats["facts"],
        failed=failed,
        partial=partial,
    )


def _entity_records(extracted: ExtractedFacts) -> list[dict[str, Any]]:
    return [{"text": e.text, "entity_type": e.entity_type} for e in extracted.entities]


def _fact_records(extracted: ExtractedFacts) -> list[dict[str, Any]]:
    return [
        {
            "head": f.head,
            "relation": f.relation,
            "tail": f.tail,
            "head_type": f.head_type,
            "tail_type": f.tail_type,
        }
        for f in extracted.facts
    ]


def main() -> None:  # pragma: no cover
    import argparse

    parser = argparse.ArgumentParser(description="Backfill fact extraction for all wiki pages")
    parser.add_argument("--force", action="store_true", help="Re-extract even if facts exist")
    args = parser.parse_args()

    repo = WikiRepo(Path(os.environ.get("WIKI_REPO_PATH", "wiki")))
    removed = prune_legacy_graph(repo)
    if removed is not None:
        print(f"[reindex_facts] removed orphaned graph at {removed}", file=sys.stderr)

    try:
        from .extraction import SpacyNerLlmExtractor
        from .llm_backends import BATCH_MAX_RETRIES, build_judgment

        # Batch context: no agent waiting, so ride out a transient proxy hiccup
        # rather than leaving the page unconverted.
        summarizer, _answerer = build_judgment(max_retries=BATCH_MAX_RETRIES)
        client = getattr(summarizer, "_client", None)
        extractor: FactExtractor = SpacyNerLlmExtractor(llm_client=client)
    except ImportError:
        from .fakes import FakeFactExtractor

        extractor = FakeFactExtractor()
        print(
            "[reindex_facts] spaCy not available; using FakeFactExtractor",
            file=sys.stderr,
        )

    # No graph_path: it now defaults to repo.graph_path, so the CLI and the MCP
    # server cannot pick different files (#19).
    result = reindex_facts(repo, extractor, force=args.force)
    if result.failed:
        print(
            f"[reindex_facts] {result.failed} page(s) left untouched — every section's "
            "extraction failed. Re-run to retry them.",
            file=sys.stderr,
        )
    if result.partial:
        print(
            f"[reindex_facts] {result.partial} page(s) kept some previous records — a "
            "section's extraction failed. Body and records may disagree until a re-run.",
            file=sys.stderr,
        )
    print(
        f"reindex_facts: processed {result.processed} page(s), "
        f"{result.graph_vertices} graph vertices"
    )


if __name__ == "__main__":
    main()
