"""Deterministic page-slug derivation."""

from __future__ import annotations

import re

__all__ = ["slugify"]

_NON_SLUG = re.compile(r"[^a-z0-9]+")


def slugify(title: str) -> str:
    """Turn a page title into a stable, filesystem-safe wiki slug.

    Lowercases, collapses any run of non-alphanumeric characters into a single
    hyphen, and trims leading/trailing hyphens. Used to name wiki pages
    deterministically so the same title always maps to the same file.
    """
    return _NON_SLUG.sub("-", title.strip().lower()).strip("-")
