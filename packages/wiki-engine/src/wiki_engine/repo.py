"""WikiRepo: the git-versioned markdown store (raw/ wiki/ schema/)."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

from .page import Page, parse_page, render_page

__all__ = ["Committer", "WikiRepo"]

Committer = Callable[[Path, str], None]

_RESERVED = {"index.md", "log.md"}


def _git_commit(root: Path, message: str) -> None:  # pragma: no cover - subprocess
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(root), "commit", "-m", message], check=True, capture_output=True
    )


class WikiRepo:
    def __init__(self, root: Path, *, committer: Committer = _git_commit) -> None:
        self.root = Path(root)
        self._committer = committer

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
