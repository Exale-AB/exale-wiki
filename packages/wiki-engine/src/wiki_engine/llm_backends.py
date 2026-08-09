"""Model-backed judgment via Hermes's OpenAI-compatible proxy.

The engine never calls an LLM vendor directly. These backends talk to the local
Hermes proxy (``hermes proxy start``), which forwards to whatever model/provider
Hermes has configured and attaches the real credentials — so "the model that
manages the wiki" is always whatever Hermes is set to.

Configuration is env-driven so the seat wrapper controls it:

- ``WIKI_LLM_BASE_URL`` — OpenAI-compatible endpoint (default the Hermes proxy).
- ``WIKI_LLM_MODEL``    — model id to request (default ``minimax/minimax-m3``).
- ``WIKI_LLM_API_KEY``  — bearer token; the proxy ignores its value but the SDK
  requires one (default ``hermes``).
- ``WIKI_LLM_TIMEOUT``  — per-request timeout in seconds (default 30); bounds how
  long a stuck proxy can stall a request before the fake fallback kicks in.
- ``WIKI_LLM_MAX_RETRIES`` — retries per request (default 0). See below.
- ``WIKI_LLM_DISABLED`` — set truthy to force the deterministic fakes.

Retries differ by caller, deliberately. The MCP server runs a single-threaded
loop with an agent waiting on it, so it defaults to **0**: a retry storm there
stacks timeout latency onto every degraded call. Batch callers have no latency
budget and nobody waiting, so `reindex_facts` asks for retries explicitly — four
transient timeouts on one seat left twelve pages unconverted, which is precisely
the case a retry fixes.

Every model call degrades gracefully: if the proxy is unreachable or errors, the
backend falls back to the deterministic fake behaviour and logs to stderr, so the
MCP server never hard-crashes on a transient proxy outage.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Sequence
from typing import Protocol

from .protocols import Answerer, Summarizer
from .source import Source

__all__ = [
    "BATCH_MAX_RETRIES",
    "HermesAnswerer",
    "HermesSummarizer",
    "build_judgment",
]

_DEFAULT_BASE_URL = "http://127.0.0.1:8645/v1"
_DEFAULT_MODEL = "minimax/minimax-m3"
_DEFAULT_API_KEY = "hermes"
_DEFAULT_TIMEOUT = 30.0
# Interactive default. Batch callers pass their own — see build_judgment.
_DEFAULT_MAX_RETRIES = 0
# What a batch CLI asks for: enough to ride out a transient proxy hiccup without
# turning one slow page into minutes of stalling.
BATCH_MAX_RETRIES = 2

_SUMMARY_MAX_TOKENS = 600
_ANSWER_MAX_TOKENS = 900
_TEMPERATURE = 0.2

_SUMMARY_SYSTEM = (
    "You are a knowledge-wiki summariser. Given a source, write a concise, factual "
    "wiki page body in markdown (1-3 short paragraphs) capturing the key facts, "
    "decisions, dates, and named entities. Do not add a title line, preamble, or "
    "commentary — output only the page body."
)
_ANSWER_SYSTEM = (
    "You answer questions strictly from the provided wiki context. Use only what the "
    "context contains; if it does not answer the question, say so plainly. Be concise "
    "and reference which context block(s) you drew from."
)


def _warn(message: str) -> None:
    print(f"[wiki_engine.llm_backends] {message}", file=sys.stderr, flush=True)


class _ChatClient(Protocol):
    """Minimal chat surface the backends need (lets tests inject a stub)."""

    def complete(self, system: str, user: str, *, max_tokens: int) -> str: ...


class OpenAICompatibleClient:
    """Thin wrapper over the ``openai`` SDK pointed at an OpenAI-compatible endpoint."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str,
        timeout: float = _DEFAULT_TIMEOUT,
        max_retries: int = _DEFAULT_MAX_RETRIES,
    ) -> None:
        from openai import OpenAI  # lazy: only needed when LLM backends are actually used

        # A request timeout means a hung proxy raises (and the backends fall back to
        # fakes) rather than wedging the single-threaded MCP loop.
        #
        # `max_retries` defaults to 0 for that same loop: a retry storm there stacks
        # timeout latency onto every degraded call while an agent waits. Batch callers
        # override it. The SDK handles the backoff, and retries only what can actually
        # succeed on a second attempt — connection errors, timeouts, 429 and 5xx. A 400
        # is not retried, because it would fail identically.
        self._client = OpenAI(
            base_url=base_url, api_key=api_key, timeout=timeout, max_retries=max_retries
        )
        self.model = model
        self.max_retries = max_retries

    def complete(self, system: str, user: str, *, max_tokens: int) -> str:
        response = self._client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=max_tokens,
            temperature=_TEMPERATURE,
        )
        return (response.choices[0].message.content or "").strip()


class HermesSummarizer(Summarizer):
    """Summarize a source into a wiki page body using the configured model."""

    def __init__(self, client: _ChatClient) -> None:
        self._client = client

    def summarize(self, source: Source) -> str:
        categories = ", ".join(source.categories) or "n/a"
        user = f"Title: {source.title}\nCategories: {categories}\n\nSource:\n{source.text}"
        try:
            body = self._client.complete(_SUMMARY_SYSTEM, user, max_tokens=_SUMMARY_MAX_TOKENS)
            if body and body.strip():
                return body.strip()
            _warn("summarize returned empty content; falling back to FakeSummarizer")
        except Exception as exc:  # noqa: BLE001 - degrade, never crash the MCP
            _warn(f"summarize failed ({exc}); falling back to FakeSummarizer")
        from .fakes import FakeSummarizer

        return FakeSummarizer().summarize(source)


class HermesAnswerer(Answerer):
    """Synthesize an answer from retrieved context using the configured model."""

    def __init__(self, client: _ChatClient) -> None:
        self._client = client

    def answer(self, question: str, context: Sequence[str]) -> str | None:
        valid = [c for c in context if c and c.strip()]
        if not valid:
            return None
        joined = "\n\n---\n\n".join(valid)
        user = f"Question: {question}\n\nWiki context:\n{joined}"
        try:
            out = self._client.complete(_ANSWER_SYSTEM, user, max_tokens=_ANSWER_MAX_TOKENS)
            if out and out.strip():
                return out.strip()
            _warn("answer returned empty content; falling back to raw context")
        except Exception as exc:  # noqa: BLE001 - degrade, never crash the MCP
            _warn(f"answer failed ({exc}); falling back to raw context")
        # Raw-context fallback: hand the agent the retrieved bodies to synthesize.
        return f"Question: {question}\n\n{joined}"


def _truthy(value: str) -> bool:
    return value.strip().lower() not in ("", "0", "false", "no")


def build_judgment(*, max_retries: int | None = None) -> tuple[Summarizer, Answerer]:
    """Return ``(summarizer, answerer)`` for the MCP server to inject.

    Hermes-backed (model-driven) when ``openai`` is importable and the LLM backend
    is not explicitly disabled; otherwise the deterministic fakes.

    ``max_retries`` lets a batch caller opt into retries that would be wrong for
    the interactive MCP loop; ``None`` means take ``WIKI_LLM_MAX_RETRIES``, which
    itself defaults to 0.
    """
    if _truthy(os.environ.get("WIKI_LLM_DISABLED", "")):
        from .fakes import FakeAnswerer, FakeSummarizer

        _warn("WIKI_LLM_DISABLED set — using deterministic fakes")
        return FakeSummarizer(), FakeAnswerer()

    base_url = os.environ.get("WIKI_LLM_BASE_URL", _DEFAULT_BASE_URL)
    model = os.environ.get("WIKI_LLM_MODEL", _DEFAULT_MODEL)
    api_key = os.environ.get("WIKI_LLM_API_KEY", _DEFAULT_API_KEY)
    try:
        timeout = float(os.environ.get("WIKI_LLM_TIMEOUT", _DEFAULT_TIMEOUT))
        retries = (
            int(os.environ.get("WIKI_LLM_MAX_RETRIES", _DEFAULT_MAX_RETRIES))
            if max_retries is None
            else max_retries
        )
        client: _ChatClient = OpenAICompatibleClient(
            base_url=base_url, model=model, api_key=api_key, timeout=timeout, max_retries=retries
        )
    except Exception as exc:  # noqa: BLE001 - openai missing or misconfigured
        from .fakes import FakeAnswerer, FakeSummarizer

        _warn(f"LLM backend unavailable ({exc}); using deterministic fakes")
        return FakeSummarizer(), FakeAnswerer()

    _warn(f"using Hermes-backed model '{model}' at {base_url} (max_retries={retries})")
    return HermesSummarizer(client), HermesAnswerer(client)
