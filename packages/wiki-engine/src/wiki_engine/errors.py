"""Wiki engine error hierarchy."""

from __future__ import annotations

__all__ = ["IngestError", "SchemaError", "WikiError"]


class WikiError(Exception):
    """Base class for all wiki-engine failures."""


class IngestError(WikiError):
    """An ingest operation could not complete."""


class SchemaError(WikiError):
    """The schema/AGENTS.md rulebook is malformed."""
