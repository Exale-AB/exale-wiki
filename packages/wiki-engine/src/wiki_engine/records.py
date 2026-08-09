"""Per-source attribution for entity and fact records.

Every record persisted in page frontmatter carries `source: <identifier>`, so a
merge can replace exactly one source's contribution and leave the rest alone.

Without it there is no way to identify a changed source's now-stale records, and
they accumulate forever — the bug class #16 was about, one level up.

Backwards-compatible: `knowledge_graph` and `mcp_server` read named keys and
ignore extras, and `relabel` preserves unknown keys. A record with no `source`
predates attribution and is treated as belonging to the page's first source.
"""

from __future__ import annotations

from typing import Any

__all__ = ["SOURCE_KEY", "merge_records", "records_for_source"]

SOURCE_KEY = "source"


def _source_of(record: Any, first_source: str | None) -> str | None:
    if not isinstance(record, dict):
        return None
    return record.get(SOURCE_KEY, first_source)


def records_for_source(records: list[Any], source: str) -> list[Any]:
    """Every record attributed to ``source``."""
    return [r for r in records if isinstance(r, dict) and r.get(SOURCE_KEY) == source]


def merge_records(
    existing: list[Any],
    extracted: list[dict[str, Any]],
    *,
    source: str,
    first_source: str | None = None,
    extraction_failed: bool = False,
) -> list[Any]:
    """Fold one source's freshly extracted records into a page's existing ones.

    ``extraction_failed`` (from ``ExtractedFacts.relations_failed``) means the
    model could not be reached, not that the source has nothing to say. The
    existing records are kept in that case: following #18, a transient timeout
    must not delete real facts. The section body still updates, so the two can
    disagree until a later run — `lint` reports that rather than hiding it.

    An empty ``extracted`` with no failure is the opposite: the source really has
    nothing, so its old records are cleared.

    Records that are not dictionaries are carried through untouched; hand-edited
    frontmatter exists and must not break an ingest.
    """
    if extraction_failed:
        return list(existing)

    # Kept records get their implied source written out, so a page becomes fully
    # attributed the first time it is touched rather than staying ambiguous.
    kept: list[Any] = []
    for record in existing:
        implied = _source_of(record, first_source)
        if implied == source:
            continue
        if isinstance(record, dict) and SOURCE_KEY not in record and implied is not None:
            record = {**record, SOURCE_KEY: implied}
        kept.append(record)

    seen: set[tuple[tuple[str, Any], ...]] = set()
    added: list[Any] = []
    for record in extracted:
        tagged = {**record, SOURCE_KEY: source}
        key = tuple(sorted(tagged.items()))
        if key in seen:
            continue
        seen.add(key)
        added.append(tagged)

    return [*kept, *added]
