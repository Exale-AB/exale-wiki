"""Tests for the standard wiki logging helpers used by skill bundles."""

from collections.abc import Callable

import wiki_utils
from wiki_utils.logging import log_action, log_batch_action

IngestFn = Callable[[str, str | None, str], None]
Recorded = list[tuple[str, str | None, str]]


def _recorder() -> tuple[Recorded, IngestFn]:
    calls: Recorded = []

    def fake_ingest(text: str, url: str | None, category: str) -> None:
        calls.append((text, url, category))

    return calls, fake_ingest


def test_log_action_capitalizes_action_and_passes_category():
    calls, fake_ingest = _recorder()

    log_action(fake_ingest, "follow-up drafted", "Anna Lindqvist", "follow-up")

    assert calls == [("Follow-up drafted: Anna Lindqvist", None, "follow-up")]


def test_log_action_appends_details_on_a_new_line():
    calls, fake_ingest = _recorder()

    log_action(fake_ingest, "risk flagged", "Acme deal", "risk", details="renewal slipping")

    text, url, category = calls[0]
    assert text == "Risk flagged: Acme deal\nrenewal slipping"
    assert url is None
    assert category == "risk"


def test_log_action_suppresses_ingest_failures():
    def failing_ingest(text: str, url: str | None, category: str) -> None:
        raise RuntimeError("wiki unavailable")

    # Must not propagate — logging is best-effort and never breaks the bundle.
    log_action(failing_ingest, "noted", "thing", "general")


def test_log_action_is_exported_from_package_root():
    assert wiki_utils.log_action is log_action


def test_log_batch_action_formats_item_count():
    calls, fake_ingest = _recorder()

    log_batch_action(fake_ingest, "inbox-triage", 5, "triage")

    assert calls == [("inbox-triage: 5 items processed", None, "triage")]


def test_log_batch_action_suppresses_ingest_failures():
    def failing_ingest(text: str, url: str | None, category: str) -> None:
        raise RuntimeError("wiki unavailable")

    log_batch_action(failing_ingest, "follow-up", 3, "follow-up")
