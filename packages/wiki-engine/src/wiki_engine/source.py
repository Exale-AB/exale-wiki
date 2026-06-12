"""A source to ingest, with a stable identity for idempotency."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import StrEnum

__all__ = ["Source", "SourceKind"]


class SourceKind(StrEnum):
    URL = "url"
    FILE = "file"
    MESSAGE = "message"


@dataclass(frozen=True)
class Source:
    kind: SourceKind
    identifier: str
    text: str
    title: str
    categories: tuple[str, ...] = field(default=())

    def identity(self) -> str:
        """Stable content hash: same kind+identifier+text -> same id."""
        digest = hashlib.sha256()
        digest.update(f"{self.kind}\x00{self.identifier}\x00{self.text}".encode())
        return digest.hexdigest()
