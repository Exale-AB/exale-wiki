"""Fact conflict detection and auto-resolution.

Detection ported from MemGraphRAG resolve_conflict.py::find_triples_sharing_head_or_tail.
Resolution prompts ported from MemGraphRAG prompt.py::PROMPT['conflict_detection'] and
PROMPT['conflict_resolution'].
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from .protocols import Fact

if TYPE_CHECKING:
    from .knowledge_graph import WikiGraph
    from .repo import WikiRepo

__all__ = [
    "Conflict",
    "HermesConflictResolver",
    "Resolution",
    "detect_fact_contradictions",
]

# Ported from MemGraphRAG prompt.py PROMPT['conflict_resolution']
_CONFLICT_RESOLUTION_SYSTEM = """\
You are an expert knowledge graph curator. Given conflicting triples and their \
source passages, resolve the conflicts.

Resolution strategies:
1. Mutual: keep the more accurate triple, discard the other.
2. Temporal: add time context if available, otherwise keep both.
3. Granularity: keep both if compatible (containment), otherwise keep the more specific.

Output a JSON object:
{"action": "keep_a"|"keep_b"|"modify_a"|"modify_b"|"keep_both", \
"reason": "explanation", "resolved_triple": ["head","relation","tail"] or null}"""


@dataclass(frozen=True)
class Conflict:
    fact_a: Fact
    fact_b: Fact
    conflict_type: Literal["mutual", "temporal", "granularity"]
    page_a: str
    page_b: str


@dataclass(frozen=True)
class Resolution:
    conflict: Conflict
    action: Literal["keep_a", "keep_b", "modify_a", "modify_b", "keep_both"]
    resolved_fact: Fact | None
    reason: str


def _warn(msg: str) -> None:
    print(f"[wiki_engine.conflicts] {msg}", file=sys.stderr, flush=True)


def detect_fact_contradictions(graph: WikiGraph) -> list[Conflict]:
    """Find facts sharing head entity + relation but with different tails.

    Ported from MemGraphRAG resolve_conflict.py::find_triples_sharing_head_or_tail.
    """
    g = graph._g  # noqa: SLF001
    conflicts: list[Conflict] = []

    # Group facts by (normalized head, normalized relation)
    head_rel_groups: dict[tuple[str, str], list[tuple[Fact, str]]] = defaultdict(list)

    for v in g.vs:
        if v["kind"] != "fact":
            continue
        fact = Fact(
            head=v["head"],
            relation=v["relation"],
            tail=v["tail"],
            head_type=v["head_type"],
            tail_type=v["tail_type"],
        )
        for pidx in g.neighbors(v.index, mode="out"):
            if g.vs[pidx]["kind"] == "passage":
                slug = g.vs[pidx]["key"]
                key = (fact.head.strip().lower(), fact.relation.strip().lower())
                head_rel_groups[key].append((fact, slug))

    for entries in head_rel_groups.values():
        if len(entries) < 2:
            continue
        seen: set[tuple[str, str]] = set()
        for i, (fa, pa) in enumerate(entries):
            for fb, pb in entries[i + 1 :]:
                if fa.tail.strip().lower() == fb.tail.strip().lower():
                    continue
                pair_key = (min(fa.tail, fb.tail), max(fa.tail, fb.tail))
                if pair_key in seen:
                    continue
                seen.add(pair_key)
                conflicts.append(
                    Conflict(
                        fact_a=fa,
                        fact_b=fb,
                        conflict_type="mutual",
                        page_a=pa,
                        page_b=pb,
                    )
                )

    return conflicts


class HermesConflictResolver:
    """Resolve conflicts via LLM. Ported from MemGraphRAG resolve_conflict.py."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def resolve(self, conflicts: list[Conflict], repo: WikiRepo | Any) -> list[Resolution]:
        resolutions: list[Resolution] = []
        for conflict in conflicts:
            body_a = ""
            body_b = ""
            if repo is not None:
                page_a = repo.read_page(conflict.page_a)
                page_b = repo.read_page(conflict.page_b)
                body_a = page_a.body if page_a else ""
                body_b = page_b.body if page_b else ""

            user_prompt = (
                f"Triple A: ({conflict.fact_a.head}, {conflict.fact_a.relation}, "
                f"{conflict.fact_a.tail})\n"
                f"Source A: {body_a[:500]}\n\n"
                f"Triple B: ({conflict.fact_b.head}, {conflict.fact_b.relation}, "
                f"{conflict.fact_b.tail})\n"
                f"Source B: {body_b[:500]}\n\n"
                f"Conflict type: {conflict.conflict_type}"
            )
            try:
                raw = self._client.complete(
                    _CONFLICT_RESOLUTION_SYSTEM, user_prompt, max_tokens=400
                )
                parsed = json.loads(raw)
                action = parsed.get("action", "keep_both")
                reason = parsed.get("reason", "")
                resolved_triple_raw = parsed.get("resolved_triple")
                resolved_fact = None
                if resolved_triple_raw and len(resolved_triple_raw) == 3:
                    resolved_fact = Fact(
                        head=resolved_triple_raw[0],
                        relation=resolved_triple_raw[1],
                        tail=resolved_triple_raw[2],
                        head_type=conflict.fact_a.head_type,
                        tail_type=conflict.fact_a.tail_type,
                    )
                resolutions.append(
                    Resolution(
                        conflict=conflict,
                        action=action,
                        resolved_fact=resolved_fact,
                        reason=reason,
                    )
                )
            except Exception as exc:
                _warn(f"conflict resolution failed ({exc}); keeping both")
                resolutions.append(
                    Resolution(
                        conflict=conflict,
                        action="keep_both",
                        resolved_fact=None,
                        reason=f"LLM error: {exc}",
                    )
                )
        return resolutions
