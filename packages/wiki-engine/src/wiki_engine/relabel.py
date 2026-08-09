"""Map persisted entity and fact types onto the current canonical vocabulary.

python -m wiki_engine.relabel            # report what would change
python -m wiki_engine.relabel --write    # apply and commit

A pure function over frontmatter already on disk: no model, no tokens,
idempotent. It exists because `reindex_facts --force` cannot do this job.

`reindex_facts` only overwrites a page's facts when re-extraction returns some
(`reindex_facts.py:50-60`), and relation extraction returns an empty tuple both
when it fails and when the text genuinely has no relations
(`extraction.py:199-201`). So a page whose extraction times out keeps its old
records verbatim while still being rewritten — after the vocabulary changed in
PR #15, twelve pages on one seat kept out-of-vocabulary endpoints through a full
`--force` run. Repairing that by hand is what this module replaces.

Deliberately importing nothing optional, so it runs on a seat that has neither
spaCy nor an LLM client installed — the case where `reindex_facts` cannot run at
all.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .language import EXCLUDED_ENTITY_TYPES, canonical_fact_type
from .page import Page
from .repo import WikiRepo

__all__ = ["RelabelResult", "relabel_facts"]

_FACT_ENDPOINTS = ("head_type", "tail_type")


@dataclass(frozen=True)
class RelabelResult:
    pages_scanned: int
    pages_changed: int
    entities_relabelled: int
    entities_dropped: int
    facts_relabelled: int
    facts_dropped: int


@dataclass
class _Tally:
    entities_relabelled: int = 0
    entities_dropped: int = 0
    facts_relabelled: int = 0
    facts_dropped: int = 0


def _relabel_entities(raw: Any, tally: _Tally) -> list[Any] | None:
    """Return the rewritten entity list, or None if it is not a list."""
    if not isinstance(raw, list):
        return None

    out: list[Any] = []
    for entity in raw:
        # Hand-edited frontmatter exists in the wild; leave what we cannot read.
        if not isinstance(entity, dict) or "entity_type" not in entity:
            out.append(entity)
            continue
        canonical = canonical_fact_type(str(entity["entity_type"]))
        if canonical in EXCLUDED_ENTITY_TYPES:
            tally.entities_dropped += 1
            continue
        if canonical != entity["entity_type"]:
            tally.entities_relabelled += 1
            entity = {**entity, "entity_type": canonical}
        out.append(entity)
    return out


def _relabel_facts(raw: Any, tally: _Tally) -> list[Any] | None:
    if not isinstance(raw, list):
        return None

    out: list[Any] = []
    for fact in raw:
        if not isinstance(fact, dict) or not all(k in fact for k in _FACT_ENDPOINTS):
            out.append(fact)
            continue
        canonical = {k: canonical_fact_type(str(fact[k])) for k in _FACT_ENDPOINTS}
        # Same rule extraction applies, so a relabelled page is indistinguishable
        # from a freshly extracted one.
        if any(value in EXCLUDED_ENTITY_TYPES for value in canonical.values()):
            tally.facts_dropped += 1
            continue
        if any(canonical[k] != fact[k] for k in _FACT_ENDPOINTS):
            tally.facts_relabelled += 1
            fact = {**fact, **canonical}
        out.append(fact)
    return out


def relabel_facts(repo: WikiRepo, *, dry_run: bool = False) -> RelabelResult:
    """Bring every page's persisted types onto the canonical vocabulary."""
    tally = _Tally()
    scanned = changed = 0

    for page in repo.list_pages():
        scanned += 1
        frontmatter = dict(page.frontmatter)
        updated = False

        for key, relabel in (("entities", _relabel_entities), ("facts", _relabel_facts)):
            if key not in frontmatter:
                continue
            rewritten = relabel(frontmatter[key], tally)
            if rewritten is not None and rewritten != frontmatter[key]:
                frontmatter[key] = rewritten
                updated = True

        if not updated:
            continue
        changed += 1
        if not dry_run:
            repo.write_page(Page(slug=page.slug, frontmatter=frontmatter, body=page.body))

    return RelabelResult(
        pages_scanned=scanned,
        pages_changed=changed,
        entities_relabelled=tally.entities_relabelled,
        entities_dropped=tally.entities_dropped,
        facts_relabelled=tally.facts_relabelled,
        facts_dropped=tally.facts_dropped,
    )


def main() -> None:  # pragma: no cover
    import argparse

    parser = argparse.ArgumentParser(
        description="Map persisted entity/fact types onto the canonical vocabulary (no LLM)"
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="apply the changes and commit; without it, only report",
    )
    args = parser.parse_args()

    repo = WikiRepo(Path(os.environ.get("WIKI_REPO_PATH", "wiki")))
    result = relabel_facts(repo, dry_run=not args.write)

    verb = "would change" if not args.write else "changed"
    print(
        f"[relabel] scanned {result.pages_scanned} pages, {verb} {result.pages_changed}; "
        f"entities {result.entities_relabelled} relabelled / {result.entities_dropped} dropped; "
        f"facts {result.facts_relabelled} relabelled / {result.facts_dropped} dropped"
    )
    if not args.write:
        print("[relabel] dry run — pass --write to apply", file=sys.stderr)
        return
    if result.pages_changed:
        repo.commit(f"chore(wiki): relabel {result.pages_changed} pages onto canonical types")


if __name__ == "__main__":  # pragma: no cover
    main()
