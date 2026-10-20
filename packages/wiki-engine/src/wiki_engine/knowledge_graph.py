"""Three-layer knowledge graph backed by igraph + GraphML.

Ported from MemGraphRAG memory.py (dedup logic, three-layer structure) and
Memgraphrag (igraph construction, PPR retrieval).
"""

from __future__ import annotations

import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import igraph as ig  # type: ignore[import-untyped]

from .protocols import Entity, ExtractedFacts, Fact
from .records import coerce_text

# The reindex CLI used to write the graph here, inside the content directory.
# Nothing ever read it back except the next CLI run, which accumulated into it
# without rebuilding, so stale vertices survived indefinitely. `WikiRepo.graph_path`
# is the one true location now; this name exists only to clean up after the old one.
LEGACY_GRAPH_FILENAME = "graph.graphml"

__all__ = ["LEGACY_GRAPH_FILENAME", "WikiGraph", "facts_from_frontmatter", "prune_legacy_graph"]

_ENTITY_KEYS = ("text", "entity_type")
_FACT_KEYS = ("head", "relation", "tail", "head_type", "tail_type")


def _warn(message: str) -> None:
    print(f"[wiki_engine.knowledge_graph] {message}", file=sys.stderr, flush=True)


def _read_records(slug: str, kind: str, raw: Any, keys: tuple[str, ...]) -> list[tuple[str, ...]]:
    """The usable records under one frontmatter key, as tuples in `keys` order.

    Frontmatter is hand-editable and model-written, so every field is untrusted.
    This runs at server startup for every page: one malformed record must cost
    that record, not the process, so each skip is a warning that names the page.
    """
    if raw is None:
        return []
    if not isinstance(raw, list):
        _warn(f"{slug}: ignoring {kind}: expected a list, got {type(raw).__name__}")
        return []
    usable: list[tuple[str, ...]] = []
    for record in raw:
        values = [coerce_text(record.get(k)) for k in keys] if isinstance(record, Mapping) else None
        if values is None or None in values:
            _warn(f"{slug}: skipping unusable {kind} record: {record!r}")
            continue
        usable.append(tuple(v for v in values if v is not None))
    return usable


def facts_from_frontmatter(slug: str, frontmatter: Mapping[str, Any]) -> ExtractedFacts:
    """Entities and facts recorded in a page's frontmatter, tolerant of bad values.

    The one place frontmatter becomes graph input; `WikiGraph.rebuild` and the MCP
    server's per-ingest update both go through it.
    """
    entities = tuple(
        Entity(*r) for r in _read_records(slug, "entity", frontmatter.get("entities"), _ENTITY_KEYS)
    )
    facts = tuple(
        Fact(*r) for r in _read_records(slug, "fact", frontmatter.get("facts"), _FACT_KEYS)
    )
    return ExtractedFacts(entities=entities, facts=facts)


def prune_legacy_graph(repo: Any) -> Path | None:
    """Delete the orphaned `wiki/graph.graphml`, if one is there.

    Safe to do rather than merely warn about: the file is derived, nothing reads
    it, and the live graph is rebuilt from page frontmatter. Both production
    seats had one deleted by hand twice, and it came back on the next run each
    time — so the cleanup belongs where the recreation used to happen.

    Deliberately narrow: it removes exactly that one path and never
    `repo.graph_path`.
    """
    orphan = repo.wiki_dir / LEGACY_GRAPH_FILENAME
    if orphan == repo.graph_path or not orphan.is_file():
        return None
    orphan.unlink()
    return orphan


def _normalize(name: str) -> str:
    return name.strip().lower()


def _fact_key(f: Fact) -> str:
    return f"{f.head}|{f.relation}|{f.tail}"


def _schema_key(f: Fact) -> str:
    return f"{f.head_type}|{f.relation}|{f.tail_type}"


class WikiGraph:
    """Three-layer knowledge graph: entity → fact → passage, with schema layer.

    Vertex types: entity, fact, schema, passage.
    Edge types: entity→fact, fact→passage, fact→schema.
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = path
        if path and path.exists():
            self._g: ig.Graph = ig.Graph.Read_GraphML(str(path))
        else:
            self._g = ig.Graph(directed=True)

    # -- vertex dedup (ported from MemGraphRAG memory.py::_get_or_create_*) ----

    def _find_vertex(self, kind: str, key: str) -> int | None:
        """Find vertex index by kind+key, or None."""
        for v in self._g.vs:
            if v["kind"] == kind and v["key"] == key:
                return v.index
        return None

    def _get_or_create(self, kind: str, key: str, **attrs: Any) -> int:
        idx = self._find_vertex(kind, key)
        if idx is not None:
            return idx
        self._g.add_vertex(kind=kind, key=key, **attrs)
        return self._g.vcount() - 1

    # -- graph mutation --------------------------------------------------------

    def update(self, slug: str, facts: ExtractedFacts) -> None:
        """Add/replace facts for a page. Idempotent — removes old passage first."""
        self.remove_page(slug)

        passage_idx = self._get_or_create("passage", slug, slug=slug)

        for fact in facts.facts:
            fk = _fact_key(fact)
            sk = _schema_key(fact)

            fact_idx = self._get_or_create(
                "fact",
                fk,
                head=fact.head,
                relation=fact.relation,
                tail=fact.tail,
                head_type=fact.head_type,
                tail_type=fact.tail_type,
            )
            schema_idx = self._get_or_create(
                "schema",
                sk,
                head_type=fact.head_type,
                relation=fact.relation,
                tail_type=fact.tail_type,
            )

            head_idx = self._get_or_create(
                "entity",
                _normalize(fact.head),
                name=fact.head,
                entity_type=fact.head_type,
            )
            tail_idx = self._get_or_create(
                "entity",
                _normalize(fact.tail),
                name=fact.tail,
                entity_type=fact.tail_type,
            )

            self._add_edge_if_missing(head_idx, fact_idx)
            self._add_edge_if_missing(tail_idx, fact_idx)
            self._add_edge_if_missing(fact_idx, passage_idx)
            self._add_edge_if_missing(fact_idx, schema_idx)

        # Standalone entities (those without facts)
        for ent in facts.entities:
            self._get_or_create(
                "entity",
                _normalize(ent.text),
                name=ent.text,
                entity_type=ent.entity_type,
            )

    def _add_edge_if_missing(self, src: int, dst: int) -> None:
        if not self._g.are_connected(src, dst):
            self._g.add_edge(src, dst)

    def remove_page(self, slug: str) -> None:
        """Remove passage vertex and its edges."""
        idx = self._find_vertex("passage", slug)
        if idx is None:
            return
        edges_to_delete = self._g.incident(idx, mode="all")
        self._g.delete_edges(edges_to_delete)
        self._g.delete_vertices(idx)

    # -- retrieval -------------------------------------------------------------

    def entity_lookup(self, entity_names: Sequence[str]) -> list[str]:
        """Return page slugs reachable from named entities (entity→fact→passage)."""
        slugs: list[str] = []
        for name in entity_names:
            eidx = self._find_vertex("entity", _normalize(name))
            if eidx is None:
                continue
            for fidx in self._g.neighbors(eidx, mode="out"):
                if self._g.vs[fidx]["kind"] != "fact":
                    continue
                for pidx in self._g.neighbors(fidx, mode="out"):
                    if self._g.vs[pidx]["kind"] != "passage":
                        continue
                    slug = self._g.vs[pidx]["key"]
                    if slug not in slugs:
                        slugs.append(slug)
        return slugs

    def ppr(
        self,
        seed_slugs: list[str],
        *,
        alpha: float = 0.85,
        top_k: int = 10,
    ) -> list[tuple[str, float]]:
        """Personalized PageRank from seed passage nodes.

        Ported from MemGraphRAG Memgraphrag.retrieve PPR approach.
        """
        if not seed_slugs or self._g.vcount() == 0:
            return []

        reset = [0.0] * self._g.vcount()
        for slug in seed_slugs:
            idx = self._find_vertex("passage", slug)
            if idx is not None:
                reset[idx] = 1.0

        if sum(reset) == 0.0:
            return []

        scores = self._g.personalized_pagerank(reset=reset, damping=alpha, directed=False)

        passage_scores: list[tuple[str, float]] = []
        for v in self._g.vs:
            if v["kind"] == "passage":
                passage_scores.append((v["key"], scores[v.index]))

        passage_scores.sort(key=lambda x: -x[1])
        return passage_scores[:top_k]

    # -- persistence -----------------------------------------------------------

    def rebuild(self, repo: Any) -> int:
        """Rebuild graph from page frontmatter. Returns vertex count."""
        self._g = ig.Graph(directed=True)
        for page in repo.list_pages():
            extracted = facts_from_frontmatter(page.slug, page.frontmatter)
            if extracted.entities or extracted.facts:
                self.update(page.slug, extracted)
        return self._g.vcount()

    def save(self) -> None:
        if self._path is not None:
            self._g.write_graphml(str(self._path))

    @property
    def stats(self) -> dict[str, int]:
        counts: dict[str, int] = {
            "entities": 0,
            "facts": 0,
            "schemas": 0,
            "passages": 0,
            "edges": self._g.ecount(),
        }
        for v in self._g.vs:
            kind = v["kind"]
            if kind == "entity":
                counts["entities"] += 1
            elif kind == "fact":
                counts["facts"] += 1
            elif kind == "schema":
                counts["schemas"] += 1
            elif kind == "passage":
                counts["passages"] += 1
        return counts
