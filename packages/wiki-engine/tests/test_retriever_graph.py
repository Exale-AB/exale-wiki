"""Tests for graph-enhanced retrieval with PPR and RRF fusion."""

import pytest

from wiki_engine.fakes import FakeEmbedder
from wiki_engine.knowledge_graph import WikiGraph
from wiki_engine.page import Page
from wiki_engine.protocols import Entity, ExtractedFacts, Fact
from wiki_engine.repo import WikiRepo
from wiki_engine.retrieval import InMemoryVectorStore, Retriever, reciprocal_rank_fusion


@pytest.fixture()
def wiki_with_graph(tmp_path):
    """A wiki repo with two pages, a populated graph, and a vector store."""
    repo = WikiRepo.init(tmp_path / "wiki", committer=lambda *_: None)
    embedder = FakeEmbedder()
    store = InMemoryVectorStore()
    graph = WikiGraph()

    page_a = Page(
        slug="acme-news",
        frontmatter={"title": "Acme News", "type": "source"},
        body="Acme Corp acquired WidgetCo last quarter.\n",
    )
    repo.write_page(page_a)
    store.upsert("acme-news", embedder.embed([page_a.body])[0])
    repo.write_index(
        "# Index\n\n## General\n- [[Acme News]] (acme-news) — Acme Corp acquired WidgetCo\n"
    )
    graph.update(
        "acme-news",
        ExtractedFacts(
            entities=(Entity("Acme Corp", "ORG"), Entity("WidgetCo", "ORG")),
            facts=(Fact("Acme Corp", "acquired", "WidgetCo", "ORG", "ORG"),),
        ),
    )

    page_b = Page(
        slug="bob-profile",
        frontmatter={"title": "Bob Profile", "type": "source"},
        body="Bob is an engineer at Acme Corp.\n",
    )
    repo.write_page(page_b)
    store.upsert("bob-profile", embedder.embed([page_b.body])[0])
    graph.update(
        "bob-profile",
        ExtractedFacts(
            entities=(Entity("Bob", "PERSON"), Entity("Acme Corp", "ORG")),
            facts=(Fact("Bob", "works_at", "Acme Corp", "PERSON", "ORG"),),
        ),
    )

    return repo, store, embedder, graph


class _EntityOnlyExtractor:
    """Simulates spaCy NER at query time (hardcoded for tests)."""

    def extract(self, text: str) -> ExtractedFacts:
        entities: list[Entity] = []
        if "Acme" in text or "acme" in text:
            entities.append(Entity("Acme Corp", "ORG"))
        if "Bob" in text or "bob" in text:
            entities.append(Entity("Bob", "PERSON"))
        return ExtractedFacts(entities=tuple(entities), facts=())


def test_retriever_with_graph_finds_related_pages(wiki_with_graph):
    repo, store, embedder, graph = wiki_with_graph
    retriever = Retriever(
        repo=repo,
        store=store,
        embedder=embedder,
        graph=graph,
        extractor=_EntityOnlyExtractor(),
    )
    results = retriever.retrieve("What did Acme Corp acquire?", k=5)
    assert "acme-news" in results


def test_retriever_graph_finds_multi_hop(wiki_with_graph):
    """Graph PPR should surface bob-profile when querying about Acme (shared entity)."""
    repo, store, embedder, graph = wiki_with_graph
    retriever = Retriever(
        repo=repo,
        store=store,
        embedder=embedder,
        graph=graph,
        extractor=_EntityOnlyExtractor(),
    )
    results = retriever.retrieve("Tell me about Acme Corp", k=5)
    assert "acme-news" in results
    assert "bob-profile" in results


def test_retriever_without_graph_falls_back(wiki_with_graph):
    """Without graph, retriever works the same as before (structural + vector)."""
    repo, store, embedder, _graph = wiki_with_graph
    retriever = Retriever(repo=repo, store=store, embedder=embedder)
    results = retriever.retrieve("Acme", k=5)
    assert isinstance(results, list)


def test_rrf_fusion():
    list_a = ["page-1", "page-2", "page-3"]
    list_b = ["page-2", "page-4", "page-1"]
    list_c = ["page-3", "page-1"]
    result = reciprocal_rank_fusion(list_a, list_b, list_c, k=3)
    assert result[0] == "page-1"
    assert len(result) == 3


def test_rrf_empty_lists():
    assert reciprocal_rank_fusion(k=3) == []
    assert reciprocal_rank_fusion([], [], k=3) == []
