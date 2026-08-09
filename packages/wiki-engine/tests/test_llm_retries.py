"""Retry policy differs by caller, and that is the point.

The MCP server runs a single-threaded loop with an agent waiting on it, so a
retry storm there stacks timeout latency onto every degraded call. A batch CLI
has nobody waiting — and four transient timeouts on one seat left twelve pages
unconverted, which is exactly what a retry fixes.
"""

from __future__ import annotations

from typing import Any

import pytest

from wiki_engine import llm_backends
from wiki_engine.llm_backends import BATCH_MAX_RETRIES, build_judgment


class _RecordingOpenAI:
    """Captures the kwargs the SDK client is built with."""

    last_kwargs: dict[str, Any] = {}

    def __init__(self, **kwargs: Any) -> None:
        type(self).last_kwargs = kwargs


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "WIKI_LLM_DISABLED",
        "WIKI_LLM_MAX_RETRIES",
        "WIKI_LLM_TIMEOUT",
        "WIKI_LLM_BASE_URL",
        "WIKI_LLM_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)
    _RecordingOpenAI.last_kwargs = {}


@pytest.fixture
def fake_sdk(monkeypatch: pytest.MonkeyPatch) -> type[_RecordingOpenAI]:
    """Stand in for `from openai import OpenAI` inside the client constructor."""
    import sys
    import types

    module = types.ModuleType("openai")
    module.OpenAI = _RecordingOpenAI  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "openai", module)
    return _RecordingOpenAI


def test_the_interactive_default_is_no_retries(fake_sdk: type[_RecordingOpenAI]) -> None:
    """The MCP loop must not grow latency; this is the pre-existing behaviour."""
    build_judgment()

    assert fake_sdk.last_kwargs["max_retries"] == 0


def test_a_batch_caller_can_ask_for_retries(fake_sdk: type[_RecordingOpenAI]) -> None:
    build_judgment(max_retries=BATCH_MAX_RETRIES)

    assert fake_sdk.last_kwargs["max_retries"] == BATCH_MAX_RETRIES
    assert BATCH_MAX_RETRIES > 0


def test_the_env_var_sets_the_default(
    fake_sdk: type[_RecordingOpenAI], monkeypatch: pytest.MonkeyPatch
) -> None:
    """So a seat can turn retries on without a code change."""
    monkeypatch.setenv("WIKI_LLM_MAX_RETRIES", "3")

    build_judgment()

    assert fake_sdk.last_kwargs["max_retries"] == 3


def test_an_explicit_argument_beats_the_env_var(
    fake_sdk: type[_RecordingOpenAI], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The caller knows whether it is interactive; the env does not."""
    monkeypatch.setenv("WIKI_LLM_MAX_RETRIES", "3")

    build_judgment(max_retries=0)

    assert fake_sdk.last_kwargs["max_retries"] == 0


def test_the_client_still_gets_its_timeout(fake_sdk: type[_RecordingOpenAI]) -> None:
    """Retries bound attempts; the timeout still bounds each one."""
    build_judgment(max_retries=2)

    assert fake_sdk.last_kwargs["timeout"] == llm_backends._DEFAULT_TIMEOUT


def test_a_broken_sdk_still_degrades_to_fakes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Retry config must not turn a missing openai into a crash."""
    import sys

    monkeypatch.setitem(sys.modules, "openai", None)

    summarizer, answerer = build_judgment(max_retries=2)

    assert type(summarizer).__name__ == "FakeSummarizer"
    assert type(answerer).__name__ == "FakeAnswerer"


def test_reindex_asks_for_batch_retries() -> None:
    """Pin the wiring: the batch CLI is the reason this exists."""
    from pathlib import Path

    source = (Path(llm_backends.__file__).parent / "reindex_facts.py").read_text(encoding="utf-8")
    assert "build_judgment(max_retries=BATCH_MAX_RETRIES)" in source
