from wiki_engine.retrieval import PgVectorStore, format_vector


def test_pgvector_store_is_constructible_without_connecting():
    # Construction must not open a connection (lazy connect on first use).
    store = PgVectorStore("postgresql://invalid/dsn", dim=8)
    assert store.dim == 8
    assert store.table == "wiki_vectors"


def test_pgvector_search_sql_uses_cosine_distance_operator():
    store = PgVectorStore("postgresql://invalid/dsn", dim=8)
    sql = store._search_sql()
    assert "<=>" in sql  # pgvector cosine-distance operator
    assert "wiki_vectors" in sql
    assert "limit" in sql.lower()


def test_format_vector_used_for_binding():
    assert format_vector([1.0, 2.0]) == "[1.0,2.0]"


def test_pgvector_upsert_sql_structure():
    store = PgVectorStore("postgresql://invalid/dsn", dim=8)
    sql = store._upsert_sql()
    assert "INSERT INTO wiki_vectors" in sql
    assert "ON CONFLICT (slug)" in sql
    assert "%s::vector" in sql
