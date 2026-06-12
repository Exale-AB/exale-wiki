"""Tests for fact conflict detection and resolution."""

from wiki_engine.conflicts import (
    Conflict,
    HermesConflictResolver,
    Resolution,
    detect_fact_contradictions,
)
from wiki_engine.knowledge_graph import WikiGraph
from wiki_engine.protocols import Entity, ExtractedFacts, Fact


def _graph_with_conflict() -> WikiGraph:
    """Build a graph where two pages disagree on the same (head, relation)."""
    graph = WikiGraph()
    graph.update(
        "page-a",
        ExtractedFacts(
            entities=(Entity("Acme", "ORG"), Entity("NYC", "GPE")),
            facts=(Fact("Acme", "headquartered_in", "NYC", "ORG", "GPE"),),
        ),
    )
    graph.update(
        "page-b",
        ExtractedFacts(
            entities=(Entity("Acme", "ORG"), Entity("London", "GPE")),
            facts=(Fact("Acme", "headquartered_in", "London", "ORG", "GPE"),),
        ),
    )
    return graph


def test_detect_finds_head_relation_conflict():
    graph = _graph_with_conflict()
    conflicts = detect_fact_contradictions(graph)
    assert len(conflicts) == 1
    c = conflicts[0]
    assert c.conflict_type == "mutual"
    tails = {c.fact_a.tail, c.fact_b.tail}
    assert tails == {"NYC", "London"}


def test_detect_no_conflict_when_same_tail():
    """Two pages with identical facts should produce no conflict."""
    graph = WikiGraph()
    fact = Fact("Acme", "headquartered_in", "NYC", "ORG", "GPE")
    for slug in ("page-a", "page-b"):
        graph.update(
            slug,
            ExtractedFacts(
                entities=(Entity("Acme", "ORG"), Entity("NYC", "GPE")),
                facts=(fact,),
            ),
        )
    assert detect_fact_contradictions(graph) == []


def test_detect_empty_graph():
    assert detect_fact_contradictions(WikiGraph()) == []


def test_detect_ignores_different_relations():
    """Different relations on the same head are not conflicts."""
    graph = WikiGraph()
    graph.update(
        "page-a",
        ExtractedFacts(
            entities=(Entity("Acme", "ORG"), Entity("NYC", "GPE")),
            facts=(Fact("Acme", "headquartered_in", "NYC", "ORG", "GPE"),),
        ),
    )
    graph.update(
        "page-b",
        ExtractedFacts(
            entities=(Entity("Acme", "ORG"), Entity("London", "GPE")),
            facts=(Fact("Acme", "founded_in", "London", "ORG", "GPE"),),
        ),
    )
    assert detect_fact_contradictions(graph) == []


def test_detect_case_insensitive():
    """Head/relation matching is case-insensitive."""
    graph = WikiGraph()
    graph.update(
        "page-a",
        ExtractedFacts(
            entities=(Entity("Acme", "ORG"), Entity("NYC", "GPE")),
            facts=(Fact("Acme", "headquartered_in", "NYC", "ORG", "GPE"),),
        ),
    )
    graph.update(
        "page-b",
        ExtractedFacts(
            entities=(Entity("ACME", "ORG"), Entity("London", "GPE")),
            facts=(Fact("ACME", "Headquartered_In", "London", "ORG", "GPE"),),
        ),
    )
    conflicts = detect_fact_contradictions(graph)
    assert len(conflicts) == 1


class _StubLlmClient:
    """Returns canned JSON for conflict resolution."""

    def __init__(self, response: str) -> None:
        self._response = response

    def complete(self, system: str, user: str, *, max_tokens: int = 400) -> str:
        return self._response


def test_hermes_resolver_keep_a():
    graph = _graph_with_conflict()
    conflicts = detect_fact_contradictions(graph)

    client = _StubLlmClient(
        '{"action": "keep_a", "reason": "NYC is more recent", "resolved_triple": null}'
    )
    resolver = HermesConflictResolver(client)
    resolutions = resolver.resolve(conflicts, repo=None)
    assert len(resolutions) == 1
    assert resolutions[0].action == "keep_a"
    assert resolutions[0].resolved_fact is None
    assert "NYC" in resolutions[0].reason


def test_hermes_resolver_modify():
    graph = _graph_with_conflict()
    conflicts = detect_fact_contradictions(graph)

    client = _StubLlmClient(
        '{"action": "modify_a", "reason": "merged", '
        '"resolved_triple": ["Acme", "headquartered_in", "NYC (2024)"]}'
    )
    resolver = HermesConflictResolver(client)
    resolutions = resolver.resolve(conflicts, repo=None)
    assert resolutions[0].action == "modify_a"
    assert resolutions[0].resolved_fact is not None
    assert resolutions[0].resolved_fact.tail == "NYC (2024)"


def test_hermes_resolver_llm_error_falls_back():
    graph = _graph_with_conflict()
    conflicts = detect_fact_contradictions(graph)

    class _BrokenClient:
        def complete(self, system: str, user: str, *, max_tokens: int = 400) -> str:
            raise RuntimeError("LLM down")

    resolver = HermesConflictResolver(_BrokenClient())
    resolutions = resolver.resolve(conflicts, repo=None)
    assert len(resolutions) == 1
    assert resolutions[0].action == "keep_both"
    assert "LLM error" in resolutions[0].reason


def test_conflict_dataclass_frozen():
    f = Fact("A", "r", "B", "T1", "T2")
    c = Conflict(fact_a=f, fact_b=f, conflict_type="mutual", page_a="p1", page_b="p2")
    try:
        c.page_a = "changed"  # type: ignore[misc]
        raise AssertionError("should be frozen")
    except AttributeError:
        pass


def test_resolution_dataclass_frozen():
    f = Fact("A", "r", "B", "T1", "T2")
    c = Conflict(fact_a=f, fact_b=f, conflict_type="mutual", page_a="p1", page_b="p2")
    r = Resolution(conflict=c, action="keep_both", resolved_fact=None, reason="ok")
    try:
        r.action = "keep_a"  # type: ignore[misc]
        raise AssertionError("should be frozen")
    except AttributeError:
        pass
