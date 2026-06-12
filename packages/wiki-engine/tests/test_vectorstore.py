import math

from wiki_engine.retrieval import InMemoryVectorStore, Retrieved, cosine, format_vector


def test_cosine_orthogonal_is_zero_and_identical_is_one():
    assert cosine([1.0, 0.0], [0.0, 1.0]) == 0.0
    assert math.isclose(cosine([1.0, 2.0], [1.0, 2.0]), 1.0)


def test_cosine_zero_vector_is_zero_not_error():
    assert cosine([0.0, 0.0], [1.0, 1.0]) == 0.0


def test_inmemory_store_upsert_and_search_ranks_by_similarity():
    store = InMemoryVectorStore()
    store.upsert("a", [1.0, 0.0, 0.0])
    store.upsert("b", [0.0, 1.0, 0.0])
    store.upsert("c", [0.9, 0.1, 0.0])
    hits = store.search([1.0, 0.0, 0.0], k=2)
    assert [h.slug for h in hits] == ["a", "c"]
    assert isinstance(hits[0], Retrieved)
    assert hits[0].score >= hits[1].score


def test_inmemory_store_upsert_replaces_same_slug():
    store = InMemoryVectorStore()
    store.upsert("a", [1.0, 0.0])
    store.upsert("a", [0.0, 1.0])
    hits = store.search([0.0, 1.0], k=5)
    assert [h.slug for h in hits] == ["a"]
    assert math.isclose(hits[0].score, 1.0)


def test_search_k_limits_results():
    store = InMemoryVectorStore()
    for i in range(5):
        store.upsert(f"p{i}", [float(i), 1.0])
    assert len(store.search([1.0, 1.0], k=3)) == 3


def test_format_vector_renders_pgvector_literal():
    assert format_vector([1.0, 2.5, -3.0]) == "[1.0,2.5,-3.0]"
