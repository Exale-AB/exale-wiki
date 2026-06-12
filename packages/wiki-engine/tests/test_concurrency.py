"""Per-repo write lock serializes concurrent mutating operations (T07)."""

import threading
from pathlib import Path

import pytest

from wiki_engine.catalog import parse_index
from wiki_engine.fakes import FakeSummarizer
from wiki_engine.ingest import ingest
from wiki_engine.repo import WikiRepo
from wiki_engine.schema import WikiSchema
from wiki_engine.source import Source, SourceKind


def test_write_lock_times_out_cleanly(tmp_path: Path):
    repo = WikiRepo.init(tmp_path, committer=lambda _r, _m: None)

    with repo.write_lock(timeout=2.0):  # noqa: SIM117 - outer lock must stay held
        # A second acquisition (separate open description) cannot get the lock and
        # must raise a clear timeout rather than hang.
        with pytest.raises(TimeoutError):
            with repo.write_lock(timeout=0.2):
                pass


def test_parallel_ingests_keep_all_pages_and_index_entries(tmp_path: Path):
    repo = WikiRepo.init(tmp_path, committer=lambda _r, _m: None)
    schema = WikiSchema()
    n = 8

    def worker(i: int) -> None:
        src = Source(
            kind=SourceKind.MESSAGE,
            identifier=f"id-{i}",
            text=f"Distinct source number {i}.",
            title=f"Source {i}",
            categories=("note",),
        )
        ingest(source=src, repo=repo, schema=schema, summarizer=FakeSummarizer())

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # No lost updates: every page exists and every catalog entry is present.
    assert len(repo.list_pages()) == n
    assert len(parse_index(repo.read_index())) == n
