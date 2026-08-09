# Language-aware fact extraction (Swedish + English)

**Status:** implemented
**Date:** 2026-08-09

## Problem

`SpacyNerLlmExtractor` hardcodes `en_core_web_sm`. Seats are bilingual — every
`seat.yaml` in exale-infra declares `languages: [sv, en]` — but that expectation
never reaches this engine. Swedish content is run through an English NER model,
which finds few entities and mislabels the ones it does find.

There is a second, structural defect. `_EXCLUDED_LABELS` holds raw English labels
(`CARDINAL`, `ORDINAL`, `MONEY`, `PERCENT`, `QUANTITY`). A Swedish model never
emits those, so on Swedish text the filter can never match and `MSR` passes
straight through.

Impact depends on the model tier. `sv_core_news_sm` emitted no `MSR` at all
across four amount-heavy Swedish sentences, so on `sm` the filter is wrong in
principle rather than leaking in practice. On `sv_core_news_md` — the tier this
design selects — it does fire (`MSR`, "12 miljoner kronor"), so the fix is load
bearing.

## Scope

Detection granularity is **per document**: any one email, document or page is
wholly Swedish or wholly English. Detect once per `extract()` call; no
chunk-level detection and no merging of entities from two models.

Three call sites are affected, and the third is easy to miss:

| Call site | Text passed |
|---|---|
| `ingest.py:111` | the source body |
| `reindex_facts.py:43` | a page body |
| `retrieval.py:153` | **the user's question** |

## Design

### 1. `language.py` — detection and the model registry

A new module in `wiki-engine`, with no new dependency.

```python
detect_language(text: str, default: str = "en") -> str   # "sv" | "en"
SPACY_MODELS = {"en": "en_core_web_md", "sv": "sv_core_news_md"}
```

Detection scores Swedish diacritics (`åäö`, weighted) against small Swedish and
English stopword sets. Ties, empty input and text with no signal return
`default`. It is a pure function with no I/O, so it is unit-testable without
spaCy installed.

Rejected alternatives: `langdetect` (unmaintained since 2021, nondeterministic
without seeding) and `lingua-language-detector` (better on short text, but a
real new dependency on every seat). For a binary sv/en decision the heuristic is
enough, and it keeps the engine dependency-light — see the lazy-import rule the
docs harness enforces.

Measured on realistic seat content: 10/12 correct. Both misses are very short
Swedish with no diacritics and no stopwords, which is the known limitation below.

### 2. Canonical entity labels

The two models emit different vocabularies. Verified by loading them, not
assumed:

```
en_core_web_md : CARDINAL DATE EVENT FAC GPE LANGUAGE LAW LOC MONEY
                 NORP ORDINAL ORG PERCENT PERSON PRODUCT QUANTITY TIME WORK_OF_ART
sv_core_news_md: EVN LOC MSR OBJ ORG PRS TME WRK

(The label sets are identical across the sm and md tiers, so the mapping is
unaffected by the tier choice.)
```

Both are mapped to one canonical vocabulary at extraction time, so the graph
holds one type per real-world concept and conflict detection works across
languages.

| Swedish | English | Canonical |
|---|---|---|
| `PRS` | `PERSON` | `PERSON` |
| `ORG` | `ORG` | `ORG` |
| `LOC` | `LOC`, `GPE` | `LOC` |
| `EVN` | `EVENT` | `EVENT` |
| `WRK` | `WORK_OF_ART` | `WORK` |
| `OBJ` | `PRODUCT` | `PRODUCT` |
| `TME` | `TIME` | `TIME` |
| — | `DATE` | `DATE` |
| — | `FAC` | `FACILITY` |
| — | `NORP`, `LAW`, `LANGUAGE` | unchanged |
| `MSR` | `CARDINAL`, `ORDINAL`, `MONEY`, `PERCENT`, `QUANTITY` | dropped |

`_EXCLUDED_LABELS` moves from raw English labels to canonical types, so the
filter applies to both languages — see the caveat under Problem about how much
that actually catches today.

**Accepted trade-off:** `GPE→LOC` discards the distinction between a
geopolitical entity and a plain place. Swedish has no `GPE`, so keeping it would
leave the two languages incomparable in the graph. Cross-language consistency is
worth more here than the finer English distinction.

### 3. `SpacyNerLlmExtractor` changes

- `__init__(..., default_language: str = "en")`.
- `spacy_model=` still accepted: when passed it forces that model and skips
  detection. This keeps the existing calls in `__main__.py:48` and
  `reindex_facts.py:89` working and `test_public_api.py` green.
- `_nlp` becomes a per-language cache rather than a single model.
- `extract()` detects the language, loads the matching model, normalises labels,
  then runs relation extraction unchanged.

### 4. Degradation

**Seats carry only `en_core_web_sm` today — neither md model is present.** A
missing model must `_warn` once and fall back to the default language's model
rather than raise, matching how `llm_backends` and `reindex_facts` already
degrade.

A missing *default* model is different: there is nothing left to degrade to, so
it raises, with a message naming the `spacy download` command that fixes it.
Silently extracting nothing would be worse than stopping. This makes the
playbook change under "Out of scope" a **prerequisite**, not a follow-up.

### 4a. Model tier

`md` on both sides, measured over 12 hand-annotated seat-like sentences:

| Content | Model | F1 |
|---|---|---|
| Swedish | `sv_core_news_sm` | 0.75 |
| Swedish | `sv_core_news_md` | **0.95** |
| English | `en_core_web_sm` | 0.75 |
| English | `en_core_web_md` | **0.80** |
| Swedish through the English model (today's behaviour) | `en_core_web_sm` | 0.67 |
| Swedish through the English model | `en_core_web_md` | **0.51** |

Two things that last pair settles. Detection matters more than model size —
0.67 → 0.95 — and a bigger English model is *worse* on Swedish text than a
smaller one, because it grows more confident that every Swedish company is a
`LOC`. Raising the tier without adding detection would have made Swedish
extraction worse.

Gold annotations are hand-written and deliberately use Swedish proper nouns,
which is hard on the English models; treat the absolute numbers as indicative.
Every model was scored against the identical set.

### 5. Testing

| What | How |
|---|---|
| `detect_language` | pure-function cases: sv, en, short, diacritic-free, empty |
| label mapping | table test over both models' full label sets |
| model selection per language | injected fake loader, so these need no model at all |
| real end-to-end | one spaCy-gated test; CI downloads both md models so it runs |

The suite must stay above the 80% coverage gate.

## Known limitations

- **Short queries.** `retrieval.py:153` extracts from the user's question. A
  three-word Swedish query is genuinely undetectable and falls back to English
  NER. A future explicit language hint through `wiki_query` would fix it;
  deliberately out of scope here.
- **Existing graphs.** `GPE→LOC` changes labels already persisted on both live
  seats. Consistency requires a `reindex_facts` run afterwards, which spends
  tokens.

## Out of scope — other repos

`deploy/ansible/wiki-mcp.yml` in exale-infra downloads only `en_core_web_sm`.
It needs **both** `en_core_web_md` and `sv_core_news_md` (54 MB + 72 MB per
seat), and that has to land **before** this change reaches a seat — otherwise
the default model is absent and extraction raises. That is an exale-infra change and is not made here.
