# Re-ingest should accumulate, not replace

**Status:** planned, not implemented
**Date:** 2026-08-09
**Issue:** #21

## Problem

Issue #21 was filed as "ingest drops a page's existing facts when re-ingest
extraction fails". Reproducing it showed the loss is larger and not conditional
on failure at all.

`ingest.py` rebuilds page frontmatter from scratch and writes `body` as the new
source's summary alone, carrying over only `sources`. Observed:

```
AFTER 1st ingest:
  sources: ['msg-1']
  facts:   [Acme --renewed--> Contract]
  body:    'Summary of Acme Renewal: Acme renewed the contract for 2026.'

AFTER 2nd ingest (extraction failed):
  sources:  ['msg-1', 'msg-2']      <- claims both
  facts:    None                     <- issue #21
  body:     'Summary of ...pricing'  <- msg-1's content is gone
```

**The page asserts provenance it no longer contains.** On a *successful*
re-ingest the facts are likewise replaced wholesale with only the new source's,
so the earlier source's contribution is discarded every time. `reindex_facts`
cannot recover it, because it re-extracts from the surviving body. The raw text
survives in `raw/`, so nothing is lost from the repo — only from the page.

This is a supported path, pinned by
`test_reingest_same_title_new_identifier_accumulates_sources`, which asserts the
accumulation of `sources` that the body then contradicts.

Issue #21 is a special case: fixing it alone would preserve facts describing a
body that was replaced anyway.

## Approach

Make a page's body and records **accumulate per source**.

### 1. Per-source sections in the body

Each source contributes one block, marked by a heading that carries its
identifier:

```markdown
## 2026-03-01 — msg-1

Summary of the first source.

## 2026-03-04 — msg-2

Summary of the second source.
```

`chunk.py` already splits bodies on markdown headings and attaches the heading to
each chunk, so retrieval gets per-source chunks and citations for free. `render`
and `catalog` take whole bodies and are unaffected.

Sections are ordered by `(date, identifier)` so output is deterministic.

Verbatim categories (`schema.verbatim_categories`) put the full source text in
the section rather than a summary, exactly as they do today for whole bodies.

### 2. Records carry their source

Every entity and fact record gains `source: <identifier>`:

```yaml
facts:
  - head: Acme
    relation: renewed
    tail: Contract
    head_type: ORG
    tail_type: MISC
    source: msg-1
```

Backwards-compatible: `knowledge_graph.py:220` and `mcp_server.py:424` read named
keys and ignore extras, and `relabel.py` preserves unknown keys through its
rewrite. A record with no `source` is treated as belonging to the page's first
source.

This makes merging exact. Re-ingesting a changed source replaces precisely its
own records; a failed extraction adds none and touches no other source's.
**Issue #21 falls out of this rather than needing its own handling.**

### 3. Migration: adopt going forward

A body with no recognised section heading is treated as one implicit section
belonging to the page's first source. New sources append sections. No token
spend, no rewrite of existing pages, and pages gain structure as they receive
more sources.

Content already lost from existing pages stays lost on the page. It remains in
`raw/`, so a rebuild is possible later if it turns out to matter.

### 4. Growth is reported, not capped

A lint rule flags pages past a schema threshold so the wiki can suggest splitting
the topic. No silent discarding — that would recreate the class of bug this
change exists to remove.

## Implementation

### Phase 1 — `sections.py` (new module, no callers)

```python
Section(identifier: str | None, date: str, text: str)

parse_sections(body: str) -> list[Section]   # unsectioned body -> one Section(identifier=None)
render_sections(sections: Sequence[Section]) -> str
upsert_section(body: str, *, identifier: str, date: str, text: str) -> str
```

`upsert_section` replaces the block for `identifier` if present, else appends,
then re-sorts. Pure functions over strings — testable with no repo, no model.

Escaping: an identifier containing a newline or markdown heading characters must
not be able to forge a section boundary. Reject or escape at the boundary; a test
pins it.

### Phase 2 — attribution helpers and `ingest`

- `records.py` (or extend `sections.py`): `merge_records(existing, new, source)` —
  drop existing records for `source`, append the new ones tagged with it.
- `ingest.py`: read `existing`, `upsert_section` the body, `merge_records` for
  `entities` and `facts`, keep `_merge_sources` as-is.
- On `relations_failed` (from #18), contribute no fact records for this source
  and leave every other source's untouched.

### Phase 3 — `reindex_facts` per section

`reindex_facts` currently extracts from the whole `page.body`, which would
produce unattributed records and flatten the attribution Phase 2 establishes. It
must extract **per section** and tag each result with that section's identifier.
`ReindexFactsResult.failed` accounting becomes per section.

### Phase 4 — lint rule and docs

- `oversized_page` rule against a schema threshold.
- `CLAUDE.md` and `README.md`: the page shape, the `source` key, and the rule
  that `sources` and sections must agree.

## Testing

| Area | Cases |
|---|---|
| `parse_sections` | unsectioned body, one section, many, out-of-order dates, identifier escaping, empty body |
| `upsert_section` | append new, replace existing, ordering is deterministic, idempotent |
| `merge_records` | replace one source's, leave others, missing `source` treated as first, dedup |
| `ingest` | two sources both survive in body and facts; failed extraction keeps the other source's facts (issue #21); same identifier re-ingested replaces its section not appends; verbatim category stores full text |
| `reindex_facts` | attribution preserved per section; failure isolated to one section |
| regression | `test_reingest_same_title_new_identifier_accumulates_sources` still passes and now also asserts both bodies survive |

## Risks and open questions

- **A changed source whose re-extraction fails.** Its section body updates but
  its facts cannot. Following #18, the safe choice is to leave the old records
  rather than delete them, which allows a section and its facts to disagree. A
  lint rule could flag it. **Not decided — resolve before Phase 2 lands.**
- **`schema.enforce_page`** runs on the merged page. Procedure pages check for
  expected markers in the body; sections must not break that. Covered by a test.
- **Page size**. Bodies now grow with source count, which affects embedding cost
  in `reindex.py` and the retrieval token budget. Chunking already bounds the
  retrieval side; the embedding side embeds whole bodies and is worth measuring.
- **Ordering by date** assumes dates are comparable strings (`today()` produces
  ISO). A source with a malformed date should sort last rather than crash.

## Sequencing

Phases 1 and 2 land together — Phase 1 alone is dead code, and Phase 2 alone has
no parser. Phase 3 must follow closely: between them, `reindex_facts --force`
would strip attribution from any page it touches. Phase 4 is independent.

Each phase branches from `main`, never from another phase's branch.
