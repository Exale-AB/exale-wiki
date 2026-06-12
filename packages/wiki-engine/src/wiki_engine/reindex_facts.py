"""Backfill CLI: extract facts for all pages and rebuild the knowledge graph.

python -m wiki_engine.reindex_facts        # process all pages
python -m wiki_engine.reindex_facts --force # re-extract even if facts exist
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from .knowledge_graph import WikiGraph
from .page import Page
from .protocols import FactExtractor
from .repo import WikiRepo

__all__ = ["ReindexFactsResult", "reindex_facts"]


@dataclass(frozen=True)
class ReindexFactsResult:
    processed: int
    graph_vertices: int


def reindex_facts(
    repo: WikiRepo,
    extractor: FactExtractor,
    *,
    graph_path: Path | None = None,
    force: bool = False,
) -> ReindexFactsResult:
    """Extract facts for all pages and rebuild the graph."""
    graph = WikiGraph(path=graph_path)
    processed = 0

    for page in repo.list_pages():
        if not force and page.frontmatter.get("facts"):
            continue

        extracted = extractor.extract(page.body)
        fm = dict(page.frontmatter)
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
    )


def main() -> None:  # pragma: no cover
    import argparse

    parser = argparse.ArgumentParser(description="Backfill fact extraction for all wiki pages")
    parser.add_argument("--force", action="store_true", help="Re-extract even if facts exist")
    args = parser.parse_args()

    repo = WikiRepo(Path(os.environ.get("WIKI_REPO_PATH", "wiki")))
    graph_path = repo.wiki_dir / "graph.graphml"

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

    result = reindex_facts(repo, extractor, graph_path=graph_path, force=args.force)
    print(
        f"reindex_facts: processed {result.processed} page(s), "
        f"{result.graph_vertices} graph vertices"
    )


if __name__ == "__main__":
    main()
