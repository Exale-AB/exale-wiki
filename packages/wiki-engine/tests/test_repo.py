from pathlib import Path

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
