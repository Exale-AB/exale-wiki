"""Tests for wiki_graph_stats and wiki_resolve_conflicts MCP tools."""

from wiki_engine.knowledge_graph import WikiGraph
from wiki_engine.mcp_server import handle_wiki_graph_stats, handle_wiki_resolve_conflicts
from wiki_engine.protocols import Entity, ExtractedFacts, Fact


def test_graph_stats_without_graph():
    result = handle_wiki_graph_stats(graph=None)
    assert result == {"available": False}


def test_graph_stats_with_graph():
    graph = WikiGraph()
    graph.update(
        "page-a",
        ExtractedFacts(
            entities=(Entity("Acme", "ORG"),),
            facts=(Fact("Acme", "acquired", "Widget", "ORG", "ORG"),),
        ),
    )
    result = handle_wiki_graph_stats(graph=graph)
    assert result["available"] is True
    assert result["entities"] >= 2
    assert result["facts"] >= 1
    assert result["passages"] >= 1


def test_resolve_conflicts_without_graph():
    result = handle_wiki_resolve_conflicts(graph=None, repo=None)
    assert result == {"available": False, "conflicts": []}


def test_resolve_conflicts_with_conflict(tmp_path):
    from wiki_engine.repo import WikiRepo

    repo = WikiRepo.init(tmp_path, committer=lambda _r, _m: None)
    graph = WikiGraph()
    graph.update(
        "page-a",
        ExtractedFacts(
            entities=(Entity("Acme", "ORG"), Entity("NYC", "GPE")),
            facts=(Fact("Acme", "hq", "NYC", "ORG", "GPE"),),
        ),
    )
    graph.update(
        "page-b",
        ExtractedFacts(
            entities=(Entity("Acme", "ORG"), Entity("London", "GPE")),
            facts=(Fact("Acme", "hq", "London", "ORG", "GPE"),),
        ),
    )
    result = handle_wiki_resolve_conflicts(graph=graph, repo=repo)
    assert result["available"] is True
    assert len(result["conflicts"]) == 1
    assert result["conflicts"][0]["page_a"] in ("page-a", "page-b")


def test_resolve_conflicts_no_conflicts():
    graph = WikiGraph()
    graph.update(
        "page-a",
        ExtractedFacts(
            entities=(Entity("Acme", "ORG"),),
            facts=(Fact("Acme", "founded", "2020", "ORG", "DATE"),),
        ),
    )
    result = handle_wiki_resolve_conflicts(graph=graph, repo=None)
    assert result["available"] is True
    assert result["conflicts"] == []
