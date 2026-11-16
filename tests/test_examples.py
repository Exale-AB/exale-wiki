"""The README quickstart is `examples/quickstart.py`; it must keep working."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_quickstart_ingests_queries_and_lints_cleanly(tmp_path: Path) -> None:
    wiki = tmp_path / "my-wiki"
    subprocess.run(["git", "init", "-q", str(wiki)], check=True)
    identity = {
        "GIT_AUTHOR_NAME": "test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    }

    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "examples" / "quickstart.py"), str(wiki)],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, **identity},
    )

    assert "Acme renewal is due 1 March" in result.stdout
    assert "cited: ('acme-renewal',)" in result.stdout
    assert "lint: []" in result.stdout
    assert (wiki / "wiki" / "acme-renewal.md").is_file()
