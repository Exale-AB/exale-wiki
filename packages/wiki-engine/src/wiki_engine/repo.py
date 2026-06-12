"""WikiRepo: the git-versioned markdown store (raw/ wiki/ schema/)."""

from __future__ import annotations

import errno
import fcntl
import subprocess
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from .page import Page, parse_page, render_page

__all__ = ["Committer", "WikiRepo"]

Committer = Callable[[Path, str], None]

_RESERVED = {"index.md", "log.md"}
_LOCK_FILE = ".wiki.lock"
_LOCK_POLL = 0.05


def _git_commit(root: Path, message: str) -> None:  # pragma: no cover - subprocess
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(root), "commit", "-m", message], check=True, capture_output=True
    )


class WikiRepo:
    def __init__(self, root: Path, *, committer: Committer = _git_commit) -> None:
        self.root = Path(root)
        self._committer = committer

    @contextmanager
    def write_lock(self, *, timeout: float = 10.0) -> Iterator[None]:
        """Exclusive, cross-process advisory lock for mutating operations.

        Serializes the read-modify-write of index.md/log.md and the git commit so
        concurrent ingests (from multiple workflows/processes) can't lose updates or
        race on the git index. Held only around the filesystem/git writes — keep
        slow model calls outside. Raises ``TimeoutError`` rather than blocking forever.

        Note: a flock is per open file description, so re-acquiring within the same
        ``with`` block self-deadlocks — never nest two ``write_lock``s in one operation.
        """
        self.root.mkdir(parents=True, exist_ok=True)
        handle = (self.root / _LOCK_FILE).open("w")
        deadline = time.monotonic() + timeout
        try:
            while True:
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError as exc:
                    if exc.errno not in (errno.EAGAIN, errno.EACCES):
                        raise
                    if time.monotonic() >= deadline:
                        raise TimeoutError(
                            f"could not acquire wiki write lock within {timeout}s"
                        ) from exc
                    time.sleep(_LOCK_POLL)
            yield
        finally:
            try:
                fcntl.flock(handle, fcntl.LOCK_UN)
            finally:
                handle.close()

    @property
    def raw_dir(self) -> Path:
        return self.root / "raw"

    @property
    def wiki_dir(self) -> Path:
        return self.root / "wiki"

    @property
    def schema_dir(self) -> Path:
        return self.root / "schema"

    @classmethod
    def init(cls, root: Path, *, committer: Committer = _git_commit) -> WikiRepo:
        repo = cls(root, committer=committer)
        for directory in (repo.raw_dir, repo.wiki_dir, repo.schema_dir):
            directory.mkdir(parents=True, exist_ok=True)
        (repo.wiki_dir / "index.md").write_text("# Index\n", encoding="utf-8")
        (repo.wiki_dir / "log.md").write_text("# Log\n", encoding="utf-8")
        # Keep the write-lock file out of git history.
        (repo.root / ".gitignore").write_text(f"{_LOCK_FILE}\n", encoding="utf-8")
        return repo

    def page_path(self, slug: str) -> Path:
        return self.wiki_dir / f"{slug}.md"

    def read_page(self, slug: str) -> Page | None:
        path = self.page_path(slug)
        if not path.exists():
            return None
        return parse_page(slug, path.read_text(encoding="utf-8"))

    def write_page(self, page: Page) -> None:
        self.page_path(page.slug).write_text(render_page(page), encoding="utf-8")

    def list_pages(self) -> list[Page]:
        return [
            parse_page(path.stem, path.read_text(encoding="utf-8"))
            for path in sorted(self.wiki_dir.glob("*.md"))
            if path.name not in _RESERVED
        ]

    def read_index(self) -> str:
        return (self.wiki_dir / "index.md").read_text(encoding="utf-8")

    def write_index(self, text: str) -> None:
        (self.wiki_dir / "index.md").write_text(text, encoding="utf-8")

    def read_log(self) -> str:
        return (self.wiki_dir / "log.md").read_text(encoding="utf-8")

    def append_log(self, line: str) -> None:
        log_path = self.wiki_dir / "log.md"
        current = log_path.read_text(encoding="utf-8").rstrip()
        log_path.write_text(f"{current}\n\n{line}\n", encoding="utf-8")

    def commit(self, message: str) -> None:
        self._committer(self.root, message)
