"""Docs harness — the markdown in this repo is checked against the code.

Three other repos (`exale-hermes`, `exale-infra`, `exale-local`) consume this
engine by reading `README.md` and `CLAUDE.md` rather than the source. A stale
module name, a wrong tool pin or a coverage gate that no longer exists in those
files is a broken instruction handed to somebody else, so they are tested like
code:

* every repo-relative path a doc mentions must exist
* every ``wiki_engine.<module>`` a doc mentions must exist
* the package table in the README must cover every workspace member
* tool pins, the coverage gate and the Python pin quoted in prose must match
  ``pyproject.toml``
* CI must actually run the commands the docs tell a human to run

A doc describing an abandoned design is legitimate history: put
``HISTORICAL RECORD`` in its first few lines, pointing at what replaced it, and
the currency checks skip it.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGES = REPO_ROOT / "packages"
ENGINE_SRC = PACKAGES / "wiki-engine" / "src" / "wiki_engine"

HISTORICAL_MARKER = "HISTORICAL RECORD"
HISTORICAL_SCAN_LINES = 5

# Markdown that is data rather than instructions: test fixtures are deliberately
# broken wikis, and graphify-out is generated.
EXCLUDED_DIRS = {
    ".venv",
    ".git",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "graphify-out",
    "fixtures",
    "node_modules",
}

PATH_TOKEN = re.compile(r"`([^`\s]+)`")
MODULE_REF = re.compile(r"wiki_engine\.([a-z_][a-z0-9_]*)")

SUFFIXES = (".py", ".md", ".toml", ".yaml", ".yml", ".json", ".sh", ".html")

# Generated and untracked: present on a dev machine, absent on a CI checkout,
# and the docs reference it conditionally. Checking it would fail in CI only.
GENERATED_PREFIX = "graphify-out/"

_TOP_LEVEL = {p.name for p in REPO_ROOT.iterdir()}


def _iter_docs() -> list[Path]:
    return sorted(
        p
        for p in REPO_ROOT.rglob("*.md")
        if not EXCLUDED_DIRS & set(p.relative_to(REPO_ROOT).parts)
    )


def _is_historical(doc: Path) -> bool:
    head = doc.read_text(encoding="utf-8").splitlines()[:HISTORICAL_SCAN_LINES]
    return any(HISTORICAL_MARKER in line for line in head)


DOCS = [d for d in _iter_docs() if not _is_historical(d)]


def _repo_paths() -> set[str]:
    """Every path in the repo, repo-relative and posix-style."""
    skip = {".git", ".venv", "__pycache__", "node_modules", ".pytest_cache", ".ruff_cache"}
    return {
        p.relative_to(REPO_ROOT).as_posix()
        for p in REPO_ROOT.rglob("*")
        if not skip & set(p.relative_to(REPO_ROOT).parts)
    }


REPO_PATHS = _repo_paths()


def _looks_like_repo_path(token: str, *, strict: bool) -> bool:
    """Is this backticked token a claim about a file in *this* repo?

    Two tiers. The entry docs are read by three other repos, so every
    path-shaped token in them must resolve (``strict``). The design notes under
    ``docs/`` legitimately cite files in other repos and in the papers they port
    from (`seat.yaml`, `rerank.py`), so there only tokens *anchored* at a real
    top-level directory of this repo are checked.
    """
    if token.startswith(("http://", "https://", "$", "~", "/", "-", ".", GENERATED_PREFIX)):
        return False
    if any(c in token for c in "()<>*|\\[]"):
        return False
    # Anchored at something that actually exists here. Also skips GitHub repo
    # slugs like `Exale-AB/exale-wiki` and wiki-internal dirs like `raw/`.
    if "/" in token and token.split("/", 1)[0] in _TOP_LEVEL:
        return True
    return strict and token.endswith(SUFFIXES)


def _path_exists(token: str) -> bool:
    """Docs name modules by their short path (`repo.py`); match any suffix."""
    token = token.rstrip("/")
    return token in REPO_PATHS or any(p.endswith("/" + token) for p in REPO_PATHS)


def _root_pyproject() -> dict:
    return tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def _workspace_members() -> list[Path]:
    return sorted(p for p in PACKAGES.iterdir() if (p / "pyproject.toml").is_file())


def _doc(name: str) -> str:
    return (REPO_ROOT / name).read_text(encoding="utf-8")


ENTRY_DOCS = ["README.md", "CLAUDE.md"]


def test_there_are_docs_to_check() -> None:
    """Guard the harness itself: an over-eager exclusion would silently pass."""
    names = {d.relative_to(REPO_ROOT).as_posix() for d in DOCS}
    assert set(ENTRY_DOCS) <= names


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.relative_to(REPO_ROOT).as_posix())
def test_referenced_paths_exist(doc: Path) -> None:
    text = doc.read_text(encoding="utf-8")
    strict = doc.relative_to(REPO_ROOT).as_posix() in ENTRY_DOCS
    missing = [
        token
        for token in PATH_TOKEN.findall(text)
        if _looks_like_repo_path(token, strict=strict) and not _path_exists(token)
    ]
    assert not missing, (
        f"{doc.relative_to(REPO_ROOT)} references paths that do not exist: {missing}"
    )


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.relative_to(REPO_ROOT).as_posix())
def test_referenced_engine_modules_exist(doc: Path) -> None:
    """`wiki_engine.reindex` in a doc is a promise that the import will work."""
    missing = sorted(
        {
            name
            for name in MODULE_REF.findall(doc.read_text(encoding="utf-8"))
            if not (ENGINE_SRC / f"{name}.py").is_file() and not (ENGINE_SRC / name).is_dir()
        }
    )
    assert not missing, (
        f"{doc.relative_to(REPO_ROOT)} names wiki_engine modules that do not exist: {missing}"
    )


def test_readme_package_table_covers_every_member() -> None:
    readme = _doc("README.md")
    undocumented = [p.name for p in _workspace_members() if p.name not in readme]
    assert not undocumented, (
        f"README.md has no entry for workspace members: {undocumented}. "
        "Every package must have an owning row in the package table."
    )


def test_every_member_is_a_declared_workspace_source() -> None:
    """A package on disk that uv does not resolve from the workspace installs from PyPI."""
    sources = _root_pyproject()["tool"]["uv"]["sources"]
    on_disk = {p.name for p in _workspace_members()}
    assert on_disk == set(sources), (
        f"packages/ and [tool.uv.sources] disagree: {on_disk ^ set(sources)}"
    )


def test_documented_optional_extras_exist() -> None:
    """`pip install wiki-engine[llm]` must name a real extra."""
    engine = tomllib.loads((PACKAGES / "wiki-engine" / "pyproject.toml").read_text("utf-8"))
    declared = set(engine["project"]["optional-dependencies"])
    advertised = set()
    for name in ENTRY_DOCS:
        advertised |= set(re.findall(r"wiki-engine\[([a-z,]+)\]", _doc(name)))
    advertised = {extra for group in advertised for extra in group.split(",")}
    assert advertised, "no doc mentions the optional extras; they should be discoverable"
    assert advertised <= declared, (
        f"docs advertise extras that wiki-engine does not declare: {sorted(advertised - declared)}"
    )


@pytest.mark.parametrize("name", ENTRY_DOCS)
def test_documented_coverage_gate_matches_pyproject(name: str) -> None:
    """The gate is quoted in both entry docs; a stale number invites ignoring it."""
    floor = _root_pyproject()["tool"]["coverage"]["report"]["fail_under"]
    assert f"{floor}% coverage gate" in _doc(name), (
        f"{name} must state the real coverage gate ({floor}%) — see pyproject fail_under"
    )


@pytest.mark.parametrize("name", ENTRY_DOCS)
def test_documented_tool_pins_match_pyproject(name: str) -> None:
    """Docs claim ruff/pyright are pinned exactly; the pins must be the real ones."""
    dev = _root_pyproject()["dependency-groups"]["dev"]
    pins = {spec for spec in dev if "==" in spec}
    text = _doc(name)
    quoted = set(re.findall(r"\b((?:ruff|pyright)==[\d.]+)", text))
    assert quoted, f"{name} does not quote the exact dev-tool pins"
    assert quoted <= pins, f"{name} quotes stale pins: {sorted(quoted - pins)}; real pins {pins}"


def test_documented_python_version_matches_pin() -> None:
    pinned = (REPO_ROOT / ".python-version").read_text(encoding="utf-8").strip()
    requires = _root_pyproject()["project"]["requires-python"]
    assert pinned in requires, f".python-version ({pinned}) is outside requires-python ({requires})"
    for name in ENTRY_DOCS:
        assert pinned in _doc(name), f"{name} must name the pinned Python ({pinned})"


def test_ci_selects_only_declared_pytest_markers() -> None:
    """CI selects on markers; an undeclared marker silently selects nothing."""
    declared = {
        line.split(":", 1)[0].strip()
        for line in _root_pyproject()["tool"]["pytest"]["ini_options"]["markers"]
    }
    ci = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    used = set(re.findall(r'-m\s+"not (\w+)"', ci))
    assert used <= declared, f"ci.yml selects on undeclared markers: {sorted(used - declared)}"


def test_ci_runs_the_commands_the_docs_promise() -> None:
    """The command a human is told to run and the gate must be the same command."""
    ci = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    documented = {"uv sync", "uv run pytest", "uv run ruff check .", "uv run pyright"}
    readme = _doc("README.md")
    for command in documented:
        assert command in readme, f"README.md no longer documents {command!r}"
        assert command in ci, f"ci.yml does not run the documented command: {command!r}"


def test_optional_dependencies_are_imported_lazily() -> None:
    """The core engine stays importable without the extras installed.

    `openai`, `fastembed` and `spacy` are optional extras. A module-level import
    of one turns a missing extra into an ImportError on `import wiki_engine` —
    which, on a seat, is the MCP server failing to start.
    """
    optional = ("openai", "fastembed", "spacy")
    banned = re.compile(rf"^(?:import|from)\s+({'|'.join(optional)})\b", re.M)
    offenders = sorted(
        f"{p.relative_to(REPO_ROOT).as_posix()}: {m.group(1)}"
        for p in PACKAGES.rglob("src/**/*.py")
        for m in banned.finditer(p.read_text(encoding="utf-8"))
    )
    assert not offenders, f"optional extras must be imported inside a function: {offenders}"


def test_engine_does_not_import_hermes() -> None:
    """`No Hermes import` is stated in both entry docs; enforce it rather than assert it."""
    banned = re.compile(r"^\s*(?:import|from)\s+hermes\w*\b", re.M)
    offenders = [
        p.relative_to(REPO_ROOT).as_posix()
        for p in PACKAGES.rglob("src/**/*.py")
        if banned.search(p.read_text(encoding="utf-8"))
    ]
    assert not offenders, f"engine packages must not import Hermes: {offenders}"
