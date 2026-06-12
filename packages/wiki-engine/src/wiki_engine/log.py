"""The append-only log.md timeline (parseable entries)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

__all__ = ["LogEntry", "format_entry", "parse_log", "today"]

_ENTRY = re.compile(r"^## \[(\d{4}-\d{2}-\d{2})\] (\w+) \| (.*)$", re.MULTILINE)


@dataclass(frozen=True)
class LogEntry:
    date: str
    op: str
    title: str


def format_entry(entry: LogEntry) -> str:
    return f"## [{entry.date}] {entry.op} | {entry.title}"


def parse_log(text: str) -> list[LogEntry]:
    return [LogEntry(d, op, title) for d, op, title in _ENTRY.findall(text)]


def today() -> str:
    return date.today().isoformat()
