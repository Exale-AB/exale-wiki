"""Entity and fact records carry the source they came from.

Without attribution, re-ingesting a changed source cannot identify its own stale
records — which is the bug class #16 was about. With it, a merge replaces exactly
one source's contribution and leaves every other alone.
"""

from __future__ import annotations

from wiki_engine.records import merge_records, records_for_source

FACT_A = {
    "head": "Acme",
    "relation": "renewed",
    "tail": "Contract",
    "head_type": "ORG",
    "tail_type": "MISC",
    "source": "msg-1",
}
FACT_B = {
    "head": "Acme",
    "relation": "priced",
    "tail": "Plan",
    "head_type": "ORG",
    "tail_type": "PRODUCT",
    "source": "msg-2",
}


def test_a_new_source_is_added_alongside_the_existing_ones() -> None:
    merged = merge_records([FACT_A], [dict(FACT_B)], source="msg-2")

    assert merged == [FACT_A, FACT_B]


def test_records_are_tagged_with_their_source() -> None:
    untagged = {k: v for k, v in FACT_B.items() if k != "source"}

    merged = merge_records([], [untagged], source="msg-2")

    assert merged[0]["source"] == "msg-2"


def test_re_ingesting_a_source_replaces_only_its_own_records() -> None:
    """The point of attribution."""
    changed = {**FACT_A, "tail": "Renewal"}

    merged = merge_records([FACT_A, FACT_B], [changed], source="msg-1")

    assert merged == [FACT_B, changed]


def test_a_failed_extraction_keeps_the_existing_records() -> None:
    """#18: a transient timeout must not delete real facts.

    The section body is updated but its facts cannot be re-extracted, so the old
    ones stay and `lint` reports the disagreement.
    """
    merged = merge_records([FACT_A, FACT_B], [], source="msg-1", extraction_failed=True)

    assert merged == [FACT_A, FACT_B]


def test_an_empty_result_clears_that_source_when_extraction_succeeded() -> None:
    """Distinct from failure: nothing found means the source has nothing to say."""
    merged = merge_records([FACT_A, FACT_B], [], source="msg-1", extraction_failed=False)

    assert merged == [FACT_B]


def test_untagged_legacy_records_belong_to_the_first_source() -> None:
    """Pages written before attribution existed still merge sensibly."""
    legacy = {k: v for k, v in FACT_A.items() if k != "source"}

    merged = merge_records([legacy], [dict(FACT_B)], source="msg-2", first_source="msg-1")

    assert merged[0]["source"] == "msg-1"
    assert merged[1]["source"] == "msg-2"


def test_untagged_legacy_records_are_replaced_when_their_source_re_ingests() -> None:
    legacy = {k: v for k, v in FACT_A.items() if k != "source"}
    changed = {**FACT_A, "tail": "Renewal"}

    merged = merge_records([legacy], [changed], source="msg-1", first_source="msg-1")

    assert merged == [changed]


def test_duplicates_within_one_source_are_collapsed() -> None:
    merged = merge_records([], [dict(FACT_A), dict(FACT_A)], source="msg-1")

    assert len(merged) == 1


def test_the_same_fact_from_two_sources_is_kept_twice() -> None:
    """Two sources independently asserting a fact is corroboration, not noise."""
    same_from_b = {**FACT_A, "source": "msg-2"}

    merged = merge_records([FACT_A], [same_from_b], source="msg-2")

    assert len(merged) == 2


def test_records_for_source_selects_one_source() -> None:
    assert records_for_source([FACT_A, FACT_B], "msg-1") == [FACT_A]


def test_malformed_records_are_carried_through_untouched() -> None:
    """Hand-edited frontmatter must not break an ingest."""
    merged = merge_records(["not-a-dict", FACT_A], [], source="msg-2")

    assert "not-a-dict" in merged
