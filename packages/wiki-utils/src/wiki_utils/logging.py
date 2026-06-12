"""Standard wiki logging patterns for all P7 bundles."""

import contextlib
from collections.abc import Callable

__all__ = ["log_action"]


def log_action(
    wiki_ingest_fn: Callable[[str, str | None, str], None],
    action: str,
    entity_name: str,
    category: str,
    details: str = "",
) -> None:
    """Log a bundle action to the wiki in standard format.

    This provides a consistent logging interface across all bundles, ensuring
    wiki entries are formatted consistently and categorized properly.

    Args:
        wiki_ingest_fn: callable(text, url, category) for wiki ingestion
        action: What happened (e.g., "follow-up drafted", "risk flagged")
        entity_name: What was acted on (contact name, deal name, meeting title)
        category: Wiki category (follow-up, meeting, risk-assessment, etc.)
        details: Optional extra details to append

    Example:
        log_action(wiki_ingest, "follow-up drafted", "Anna Lindqvist", "follow-up")
    """
    text = f"{action.capitalize()}: {entity_name}"
    if details:
        text += f"\n{details}"

    with contextlib.suppress(Exception):
        wiki_ingest_fn(text, None, category)


def log_batch_action(
    wiki_ingest_fn: Callable[[str, str | None, str], None],
    bundle_name: str,
    action_count: int,
    category: str,
) -> None:
    """Log a batch action (e.g., '5 emails drafted')."""
    text = f"{bundle_name}: {action_count} items processed"
    with contextlib.suppress(Exception):
        wiki_ingest_fn(text, None, category)
