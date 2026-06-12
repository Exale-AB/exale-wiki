"""Tests for the WikiGraph three-layer knowledge graph."""

from wiki_engine.knowledge_graph import WikiGraph
from wiki_engine.page import Page
from wiki_engine.protocols import Entity, ExtractedFacts, Fact
from wiki_engine.repo import WikiRepo


def _sample_facts() -> ExtractedFacts:
    return ExtractedFacts(
        entities=(
            Entity("Acme Corp", "ORG"),
            Entity("WidgetCo", "ORG"),
            Entity("Jane Smith", "PERSON"),
        ),
        facts=(
            Fact("Acme Corp", "acquired", "WidgetCo", "ORG", "ORG"),
            Fact("Jane Smith", "announced", "Acme Corp", "PERSON", "ORG"),
        ),
    )


def test_empty_graph():
    g = WikiGraph()
    assert g.stats["entities"] == 0
    assert g.stats["facts"] == 0
    assert g.stats["schemas"] == 0
    assert g.stats["passages"] == 0


def test_update_adds_vertices_and_edges():
    g = WikiGraph()
    g.update("acme-acquires-widgetco", _sample_facts())
    assert g.stats["entities"] == 3
    assert g.stats["facts"] == 2
    assert g.stats["schemas"] == 2
    assert g.stats["passages"] == 1


def test_update_is_idempotent():
    g = WikiGraph()
    g.update("page-a", _sample_facts())
    g.update("page-a", _sample_facts())
    assert g.stats["passages"] == 1
    assert g.stats["facts"] == 2


def test_update_second_page_shares_entities():
    g = WikiGraph()
    g.update("page-a", _sample_facts())
    g.update(
        "page-b",
        ExtractedFacts(
            entities=(Entity("Acme Corp", "ORG"), Entity("Bob", "PERSON")),
            facts=(Fact("Bob", "works_at", "Acme Corp", "PERSON", "ORG"),),
        ),
    )
    assert g.stats["passages"] == 2
    assert g.stats["entities"] == 4  # Acme, WidgetCo, Jane, Bob


def test_entity_lookup():
    g = WikiGraph()
    g.update("page-a", _sample_facts())
    g.update(
        "page-b",
        ExtractedFacts(
            entities=(Entity("Acme Corp", "ORG"), Entity("Bob", "PERSON")),
            facts=(Fact("Bob", "works_at", "Acme Corp", "PERSON", "ORG"),),
        ),
    )
    slugs = g.entity_lookup(["Acme Corp"])
    assert "page-a" in slugs
    assert "page-b" in slugs


def test_entity_lookup_normalizes_case():
    g = WikiGraph()
    g.update("page-a", _sample_facts())
    slugs = g.entity_lookup(["acme corp"])
    assert "page-a" in slugs


def test_entity_lookup_no_match():
    g = WikiGraph()
    g.update("page-a", _sample_facts())
    assert g.entity_lookup(["Nonexistent"]) == []


def test_ppr_returns_ranked_passages():
    g = WikiGraph()
    g.update("page-a", _sample_facts())
    g.update(
        "page-b",
        ExtractedFacts(
            entities=(Entity("Acme Corp", "ORG"), Entity("Bob", "PERSON")),
            facts=(Fact("Bob", "works_at", "Acme Corp", "PERSON", "ORG"),),
        ),
    )
    ranked = g.ppr(["page-a"], top_k=5)
    slugs = [slug for slug, _score in ranked]
    assert "page-a" in slugs
    assert "page-b" in slugs


def test_ppr_empty_seeds():
    g = WikiGraph()
    g.update("page-a", _sample_facts())
    assert g.ppr([], top_k=5) == []


def test_remove_page():
    g = WikiGraph()
    g.update("page-a", _sample_facts())
    assert g.stats["passages"] == 1
    g.remove_page("page-a")
    assert g.stats["passages"] == 0


def test_remove_page_nonexistent():
    g = WikiGraph()
    g.remove_page("nope")  # should not raise


def test_save_and_load(tmp_path):
    path = tmp_path / "graph.graphml"
    g = WikiGraph(path=path)
    g.update("page-a", _sample_facts())
    g.save()

    assert path.exists()

    g2 = WikiGraph(path=path)
    assert g2.stats["passages"] == 1
    assert g2.stats["facts"] == 2
    assert g2.stats["entities"] == 3


def test_rebuild_from_repo(tmp_path):
    repo = WikiRepo.init(tmp_path / "wiki", committer=lambda *_: None)
    repo.write_page(
        Page(
            slug="acme",
            frontmatter={
                "title": "Acme",
                "type": "source",
                "entities": [{"text": "Acme Corp", "entity_type": "ORG"}],
                "facts": [
                    {
                        "head": "Acme Corp",
                        "relation": "acquired",
                        "tail": "WidgetCo",
                        "head_type": "ORG",
                        "tail_type": "ORG",
                    },
                ],
            },
            body="Acme Corp acquired WidgetCo.\n",
        )
    )

    g = WikiGraph()
    count = g.rebuild(repo)
    assert count > 0
    assert g.stats["passages"] == 1
    assert g.stats["facts"] == 1
    slugs = g.entity_lookup(["Acme Corp"])
    assert "acme" in slugs
