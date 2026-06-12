"""Tests for the fact backfill CLI."""

import pytest

from wiki_engine.fakes import FakeFactExtractor
from wiki_engine.page import Page
from wiki_engine.reindex_facts import reindex_facts
from wiki_engine.repo import WikiRepo


@pytest.fixture()
def wiki_repo(tmp_path):
    repo = WikiRepo.init(tmp_path / "wiki", committer=lambda *_: None)
    repo.write_page(
        Page(
            slug="page-a",
            frontmatter={"title": "Page A", "type": "source"},
            body="Acme Corp acquired WidgetCo.\n",
        )
    )
    repo.write_page(
        Page(
            slug="page-b",
            frontmatter={"title": "Page B", "type": "source"},
            body="Bob works at Acme Corp.\n",
        )
    )
    return repo


def test_reindex_facts_processes_all_pages(wiki_repo):
    result = reindex_facts(wiki_repo, extractor=FakeFactExtractor())
    assert result.processed == 2
    assert result.graph_vertices >= 0


def test_reindex_facts_skips_pages_with_existing_facts(wiki_repo):
    wiki_repo.write_page(
        Page(
            slug="page-a",
            frontmatter={
                "title": "Page A",
                "type": "source",
                "facts": [
                    {
                        "head": "X",
                        "relation": "r",
                        "tail": "Y",
                        "head_type": "T",
                        "tail_type": "T",
                    }
                ],
            },
            body="Acme Corp acquired WidgetCo.\n",
        )
    )
    result = reindex_facts(wiki_repo, extractor=FakeFactExtractor(), force=False)
    assert result.processed == 1  # only page-b processed


def test_reindex_facts_force_reprocesses_all(wiki_repo):
    wiki_repo.write_page(
        Page(
            slug="page-a",
            frontmatter={
                "title": "Page A",
                "type": "source",
                "facts": [
                    {
                        "head": "X",
                        "relation": "r",
                        "tail": "Y",
                        "head_type": "T",
                        "tail_type": "T",
                    }
                ],
            },
            body="Acme Corp acquired WidgetCo.\n",
        )
    )
    result = reindex_facts(wiki_repo, extractor=FakeFactExtractor(), force=True)
    assert result.processed == 2
