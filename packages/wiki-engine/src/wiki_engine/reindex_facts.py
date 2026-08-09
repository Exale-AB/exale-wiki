"""Backfill CLI: extract facts for all pages and rebuild the knowledge graph.

python -m wiki_engine.reindex_facts        # process all pages
python -m wiki_engine.reindex_facts --force # re-extract even if facts exist

`--force` means re-extract from scratch, so a page whose extraction returns
nothing has its records *cleared*. It used to preserve them, because a failed
extraction and an empty one were the same empty tuple — so a page that timed out
kept its old records while still being rewritten, and the mtime claimed
otherwise. Twelve pages on one seat survived a full --force run that way.

A page whose extraction actually fails is now left untouched and counted in
`ReindexFactsResult.failed`. Untouched rather than cleared, because a transient
timeout must not delete real facts, and rewriting it would move the mtime for
nothing.

Note the cost asymmetry: this CLI spends tokens. If all you need is to bring
persisted types onto a changed vocabulary, `python -m wiki_engine.relabel` does
that as a pure data migration.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from .knowledge_graph import WikiGraph, prune_legacy_graph
from .page import Page
from .protocols import FactExtractor
from .repo import WikiRepo

__all__ = ["ReindexFactsResult", "reindex_facts"]


@dataclass(frozen=True)
class ReindexFactsResult:
    processed: int
    graph_vertices: int
    # Pages whose relation extraction failed and were therefore left untouched.
    # Reported so a run that converted less than it looks like cannot pass for a
    # complete one — see the module docstring.
    failed: int = 0


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

    for page in repo.list_pages():
        if not force and page.frontmatter.get("facts"):
            continue

        extracted = extractor.extract(page.body)

        # Extraction failed rather than finding nothing. Leave the page entirely
        # alone: rewriting it would move the mtime while the records stayed
        # stale, which is what let a --force run look complete when it was not.
        # Untouched means a re-run picks it up again.
        if extracted.relations_failed:
            failed += 1
            continue

        fm = dict(page.frontmatter)
        # Assign unconditionally, so an empty result *clears* the old records
        # rather than preserving them. That is what --force is asked to do.
        fm.pop("entities", None)
        fm.pop("facts", None)
        if extracted.entities:
            fm["entities"] = [
                {"text": e.text, "entity_type": e.entity_type} for e in extracted.entities
            ]
        if extracted.facts:
            fm["facts"] = [
                {
                    "head": f.head,
                    "relation": f.relation,
                    "tail": f.tail,
                    "head_type": f.head_type,
                    "tail_type": f.tail_type,
                }
                for f in extracted.facts
            ]
        repo.write_page(Page(slug=page.slug, frontmatter=fm, body=page.body))

        if extracted.entities or extracted.facts:
            graph.update(page.slug, extracted)
        processed += 1

    graph.save()
    return ReindexFactsResult(
        processed=processed,
        graph_vertices=graph.stats["entities"] + graph.stats["facts"],
        failed=failed,
    )


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
        from .llm_backends import build_judgment

        summarizer, _answerer = build_judgment()
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
            f"[reindex_facts] {result.failed} page(s) left untouched — extraction failed. "
            "Re-run to retry them.",
            file=sys.stderr,
        )
    print(
        f"reindex_facts: processed {result.processed} page(s), "
        f"{result.graph_vertices} graph vertices"
    )


if __name__ == "__main__":
    main()
