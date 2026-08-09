"""There is one graph file, and the repo owns where it lives.

The MCP server and the reindex CLI each computed the path themselves and
disagreed — `WIKI_REPO_PATH/graph.graphml` against `wiki/graph.graphml`. Nothing
read the CLI's copy except the next CLI run, which accumulated into it without
ever rebuilding, so stale vertices survived indefinitely. Both production seats
grew a divergent second graph, and deleting it did not help: every `--force` run
recreated it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from wiki_engine.fakes import FakeFactExtractor
from wiki_engine.knowledge_graph import LEGACY_GRAPH_FILENAME, prune_legacy_graph
from wiki_engine.page import Page
from wiki_engine.reindex_facts import reindex_facts
from wiki_engine.repo import WikiRepo


@pytest.fixture
def repo(tmp_path: Path) -> WikiRepo:
    repo = WikiRepo(tmp_path / "wiki")
    repo.init(tmp_path / "wiki")
    repo.write_page(Page(slug="a", frontmatter={"title": "a"}, body="body"))
    return repo


def test_the_repo_owns_the_graph_path(repo: WikiRepo) -> None:
    """One definition, so two callers cannot disagree again."""
    assert repo.graph_path == repo.root / "graph.graphml"


def test_the_graph_lives_beside_the_content_not_inside_it(repo: WikiRepo) -> None:
    """`wiki/` is the system of record; the graph is derived and rebuildable."""
    assert repo.graph_path.parent == repo.root
    assert repo.graph_path.parent != repo.wiki_dir


def test_reindex_writes_the_repo_graph_by_default(repo: WikiRepo) -> None:
    """The CLI used to default to its own path — that is the whole bug."""
    reindex_facts(repo, FakeFactExtractor())

    assert repo.graph_path.exists()
    assert not (repo.wiki_dir / LEGACY_GRAPH_FILENAME).exists()


def test_an_explicit_graph_path_is_still_honoured(repo: WikiRepo, tmp_path: Path) -> None:
    """Tests and callers that pass one keep working."""
    custom = tmp_path / "elsewhere.graphml"

    reindex_facts(repo, FakeFactExtractor(), graph_path=custom)

    assert custom.exists()


def test_prune_removes_the_orphan(repo: WikiRepo) -> None:
    orphan = repo.wiki_dir / LEGACY_GRAPH_FILENAME
    orphan.write_text("<graphml/>", encoding="utf-8")

    removed = prune_legacy_graph(repo)

    assert removed == orphan
    assert not orphan.exists()


def test_prune_is_a_no_op_when_there_is_no_orphan(repo: WikiRepo) -> None:
    assert prune_legacy_graph(repo) is None


def test_prune_never_touches_the_real_graph(repo: WikiRepo) -> None:
    """A cleanup that deletes the live graph would be worse than the orphan."""
    repo.graph_path.write_text("<graphml/>", encoding="utf-8")
    (repo.wiki_dir / LEGACY_GRAPH_FILENAME).write_text("<graphml/>", encoding="utf-8")

    prune_legacy_graph(repo)

    assert repo.graph_path.exists()


def test_prune_leaves_pages_alone(repo: WikiRepo) -> None:
    (repo.wiki_dir / LEGACY_GRAPH_FILENAME).write_text("<graphml/>", encoding="utf-8")

    prune_legacy_graph(repo)

    assert {p.slug for p in repo.list_pages()} == {"a"}
