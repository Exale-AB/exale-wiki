from pathlib import Path

import pytest

from wiki_engine.catalog import CatalogEntry, parse_index
from wiki_engine.log import LogEntry, parse_log
from wiki_engine.page import Page
from wiki_engine.repo import WikiRepo


def _recording_committer():
    calls: list[tuple[Path, str]] = []

    def committer(root: Path, message: str) -> None:
        calls.append((root, message))

    return committer, calls


def _repo(tmp_path: Path) -> WikiRepo:
    committer, _ = _recording_committer()
    return WikiRepo.init(tmp_path, committer=committer)


def test_init_creates_three_layers_and_seed_files(tmp_path: Path):
    repo = _repo(tmp_path)
    assert repo.raw_dir.is_dir() and repo.wiki_dir.is_dir() and repo.schema_dir.is_dir()
    assert (repo.wiki_dir / "index.md").read_text() == "# Index\n"
    assert (repo.wiki_dir / "log.md").read_text() == "# Log\n"


def test_write_then_read_page_round_trips(tmp_path: Path):
    repo = _repo(tmp_path)
    page = Page(slug="acme", frontmatter={"title": "Acme AB"}, body="Body [[Anna]].")
    repo.write_page(page)
    loaded = repo.read_page("acme")
    assert loaded is not None
    assert loaded.title == "Acme AB"
    assert loaded.wikilinks == ("Anna",)


def test_read_missing_page_returns_none(tmp_path: Path):
    assert _repo(tmp_path).read_page("nope") is None


def test_list_pages_excludes_index_and_log(tmp_path: Path):
    repo = _repo(tmp_path)
    repo.write_page(Page(slug="a", frontmatter={"title": "A"}, body="x"))
    repo.write_page(Page(slug="b", frontmatter={"title": "B"}, body="y"))
    assert sorted(p.slug for p in repo.list_pages()) == ["a", "b"]


def test_append_log_keeps_existing_and_adds_entry(tmp_path: Path):
    repo = _repo(tmp_path)
    repo.append_log("## [2026-06-04] ingest | Acme AB")
    text = repo.read_log()
    assert text.startswith("# Log")
    assert "## [2026-06-04] ingest | Acme AB" in text


def test_commit_delegates_to_injected_committer(tmp_path: Path):
    committer, calls = _recording_committer()
    repo = WikiRepo.init(tmp_path, committer=committer)
    repo.commit("hello")
    assert calls[-1] == (tmp_path, "hello")


# --- T12: transaction context manager ----------------------------------------


def test_transaction_commits_once_on_clean_exit(tmp_path: Path):
    """transaction() commits exactly once with the given message on clean exit."""
    committer, calls = _recording_committer()
    repo = WikiRepo.init(tmp_path, committer=committer)

    with repo.transaction("test commit") as txn:
        txn.put_page(Page(slug="a", frontmatter={"title": "A"}, body="x"))
        txn.catalog(CatalogEntry(title="A", slug="a", category="Ops", summary="x"))
        txn.log(LogEntry(date="2026-06-12", op="ingest", title="A"))

    commit_msgs = [msg for _, msg in calls]
    assert commit_msgs.count("test commit") == 1

    # Index and log were written
    assert "(a)" in repo.read_index()
    log = parse_log(repo.read_log())
    assert any(e.title == "A" for e in log)


def test_transaction_does_not_commit_on_abort(tmp_path: Path):
    """txn.abort() → no commit, buffered catalog/log discarded."""
    committer, calls = _recording_committer()
    repo = WikiRepo.init(tmp_path, committer=committer)
    index_before = repo.read_index()
    log_before = repo.read_log()

    with repo.transaction("should not commit") as txn:
        txn.catalog(CatalogEntry(title="A", slug="a", category="Ops", summary="x"))
        txn.log(LogEntry(date="2026-06-12", op="test", title="A"))
        txn.abort()

    assert not any(msg == "should not commit" for _, msg in calls)
    assert repo.read_index() == index_before
    assert repo.read_log() == log_before


def test_transaction_does_not_commit_on_exception(tmp_path: Path):
    """Exception in body → no commit, exception propagates, lock released."""
    committer, calls = _recording_committer()
    repo = WikiRepo.init(tmp_path, committer=committer)

    with pytest.raises(ValueError, match="boom"), repo.transaction("should not commit") as txn:
        txn.put_page(Page(slug="a", frontmatter={"title": "A"}, body="x"))
        raise ValueError("boom")

    assert not any(msg == "should not commit" for _, msg in calls)
    # Lock is released — a second transaction can acquire without deadlocking.
    with repo.transaction("second") as _txn:
        pass


def test_transaction_coalesces_index_writes(tmp_path: Path):
    """Two catalog() calls → index.md written once, both entries present."""
    committer, calls = _recording_committer()
    repo = WikiRepo.init(tmp_path, committer=committer)

    with repo.transaction("two entries") as txn:
        txn.put_page(Page(slug="a", frontmatter={"title": "A"}, body="x"))
        txn.put_page(Page(slug="b", frontmatter={"title": "B"}, body="y"))
        txn.catalog(CatalogEntry(title="A", slug="a", category="Ops", summary="first"))
        txn.catalog(CatalogEntry(title="B", slug="b", category="Ops", summary="second"))
        txn.log(LogEntry(date="2026-06-12", op="test", title="A"))
        txn.log(LogEntry(date="2026-06-12", op="test", title="B"))

    index = repo.read_index()
    entries = parse_index(index)
    slugs = {e.slug for e in entries}
    assert {"a", "b"} == slugs

    log = parse_log(repo.read_log())
    assert len([e for e in log if e.op == "test"]) == 2


def test_transaction_is_single_locked(tmp_path: Path):
    """Re-entering write_lock inside a transaction body self-deadlocks."""
    repo = _repo(tmp_path)

    with repo.transaction("outer") as _txn:  # noqa: SIM117 - nested with needed for clarity
        with pytest.raises(TimeoutError):
            with repo.write_lock(timeout=0.2):
                pass
