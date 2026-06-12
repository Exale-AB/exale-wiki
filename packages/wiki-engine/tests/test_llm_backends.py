"""Tests for the model-backed judgment backends (HermesSummarizer/HermesAnswerer).

A stub chat client is injected, so these run with no ``openai`` dependency and no
network — they exercise the prompt plumbing and the graceful-degradation paths.
"""

import pytest

from wiki_engine.fakes import FakeAnswerer, FakeSummarizer
from wiki_engine.llm_backends import (
    HermesAnswerer,
    HermesSummarizer,
    OpenAICompatibleClient,
    build_judgment,
)
from wiki_engine.source import Source, SourceKind


def test_openai_client_applies_timeout_and_disables_retry_storm():
    # Constructing the client makes no network call; it just configures the SDK so a
    # hung proxy fails fast (and the backends' fallback catches it) instead of wedging.
    client = OpenAICompatibleClient(
        base_url="http://127.0.0.1:9/v1", model="m", api_key="k", timeout=4.0
    )

    assert client._client.timeout == 4.0
    assert client._client.max_retries == 0


class StubClient:
    """Records the last call and returns a scripted reply (or raises)."""

    def __init__(self, reply: str = "", *, raises: Exception | None = None) -> None:
        self.reply = reply
        self.raises = raises
        self.last_system: str | None = None
        self.last_user: str | None = None

    def complete(self, system: str, user: str, *, max_tokens: int) -> str:
        self.last_system, self.last_user = system, user
        if self.raises is not None:
            raise self.raises
        return self.reply


def _source() -> Source:
    return Source(
        kind=SourceKind.MESSAGE,
        identifier="id-1",
        text="Decision: migrate to Slack by June 30.\nOwner: Nandan.",
        title="Slack Migration",
        categories=("decision",),
    )


def test_summarizer_returns_model_output():
    client = StubClient(reply="The team will migrate to Slack by June 30 (owner: Nandan).")

    body = HermesSummarizer(client).summarize(_source())

    assert body == "The team will migrate to Slack by June 30 (owner: Nandan)."
    # The source text and title are handed to the model.
    assert "Slack Migration" in (client.last_user or "")
    assert "migrate to Slack" in (client.last_user or "")


def test_summarizer_falls_back_to_fake_on_error():
    client = StubClient(raises=RuntimeError("proxy down"))
    source = _source()

    body = HermesSummarizer(client).summarize(source)

    assert body == FakeSummarizer().summarize(source)


def test_summarizer_falls_back_on_empty_reply():
    source = _source()

    body = HermesSummarizer(StubClient(reply="   ")).summarize(source)

    assert body == FakeSummarizer().summarize(source)


def test_answerer_returns_none_for_empty_context():
    assert HermesAnswerer(StubClient(reply="x")).answer("q", []) is None
    assert HermesAnswerer(StubClient(reply="x")).answer("q", ["  ", ""]) is None


def test_answerer_returns_model_output_with_context():
    client = StubClient(reply="Slack migration is due June 30.")

    out = HermesAnswerer(client).answer("when is slack due?", ["Migrate to Slack by June 30."])

    assert out == "Slack migration is due June 30."
    assert "when is slack due?" in (client.last_user or "")
    assert "Migrate to Slack by June 30." in (client.last_user or "")


def test_answerer_falls_back_to_raw_context_on_error():
    client = StubClient(raises=RuntimeError("timeout"))

    out = HermesAnswerer(client).answer("q", ["page one", "page two"])

    assert out is not None
    assert "Question: q" in out
    assert "page one" in out and "page two" in out


def test_build_judgment_uses_fakes_when_disabled(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("WIKI_LLM_DISABLED", "1")

    summarizer, answerer = build_judgment()

    assert isinstance(summarizer, FakeSummarizer)
    assert isinstance(answerer, FakeAnswerer)
