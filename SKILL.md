---
name: knowledge-wiki
description: Use to read from and write to the seat's Self-Improving Knowledge Wiki via the `wiki-engine` MCP server. Trigger whenever you need grounded facts about the customer, need to remember something durably, want to check whether the wiki already knows something, or want to keep the wiki healthy. Covers query, context, search, get, ingest, lint, and graph tools.
---

# Knowledge Wiki (wiki-engine MCP)

The `wiki-engine` MCP server is this seat's long-term memory: a git-versioned
markdown knowledge base (`raw/` sources, `wiki/` pages, `schema/` rulebook) plus a
derived knowledge graph. It is the **system of record** for durable facts about the
customer, their processes, contacts, and decisions.

**Core principle — the wiki returns raw context, not final answers.** Retrieval
tools hand you grounded snippets with citations; *you* write the natural-language
reply to the user. Never present wiki text verbatim as if it were your own memory —
cite the page slugs.

## When to reach for the wiki

- **Before answering anything about the customer** (people, processes, preferences,
  history) — retrieve first, don't guess.
- **Before ingesting** — search first so you don't create duplicate pages.
- **After learning a durable fact** (a decision, a process, a contact detail) — ingest
  it so it's "never asked twice."
- **Periodically / when asked to tidy up** — lint and resolve conflicts.

## Choosing the right tool

| Goal | Tool | Cost |
|---|---|---|
| Grounded snippets to reason over yourself | `wiki_context` | cheap, no LLM |
| A synthesized answer with citations | `wiki_query` | LLM call |
| "Does a page about X already exist?" / browse | `wiki_search` | cheap, no bodies |
| Read one page in full | `wiki_get` | cheap |
| Remember a new fact/source | `wiki_ingest` | LLM (summarize + extract) |
| Health check: orphans, contradictions, stale | `wiki_lint` | cheap |
| Graph size (entities/facts/…) | `wiki_graph_stats` | cheap |
| Find contradicting facts in the graph | `wiki_resolve_conflicts` | cheap |

**Default retrieval path:** `wiki_context` for grounding your own reasoning;
`wiki_query` only when you specifically want the engine to synthesize the answer.

## Tools

### `wiki_context` — grounding material (preferred for retrieval)
Ranked page snippets + citations, **no synthesis, no LLM call.** Use this to ground
your own reasoning.
- `query` (required) — what to retrieve context about.
- `k` (default 5) — max pages to consider.
- `token_budget` (default 2000) — approx cap on returned context.
- Returns: `{ context: [{slug, title, heading, text, score}], citations: [slug…] }`.

### `wiki_query` — synthesized answer
Retrieves, then formats a grounded answer with citations.
- `query` (required).
- `file_as_new_page` (default false) — if true, files the answer as a new page
  ("never asked twice"). Only set true when the answer is worth persisting.
- Returns: `{ answer, citations: [slug…], mode: "model"|"fake", degraded: bool }`.
- **Check `degraded`:** when true the model backend is unavailable and the answer is a
  fallback — treat it as low-confidence.

### `wiki_search` — cheap existence check / browse
Ranked hits (`slug, title, summary, category, score`), **no page bodies.** Run this
before `wiki_ingest` to avoid duplicates.
- `query` (required), `k` (default 10).
- Returns: `{ results: [{slug, title, summary, category, score}] }`.

### `wiki_get` — read one page
- `slug` (required).
- Returns: `{ found, slug, title, frontmatter, body }` or `{ found: false, slug }`.

### `wiki_ingest` — remember a source
Turns a source into a summarized page and updates the index/log + graph. Idempotent:
re-ingesting identical text dedupes; off-limits categories are refused before any work.
- `category` (required) — e.g. `email`, `process`, `faq`, `contact`.
- Provide **exactly one** of `source_text` (raw text/body/note) or `source_url`.
- `contributor` (optional) — which workflow/bundle/person added this (provenance).
- Returns: `{ slug, title, status, sources_merged }`.
- **Workflow:** `wiki_search` first → ingest only if nothing relevant exists.

### `wiki_lint` — self-improvement
Reports violations (orphaned pages, contradictions, stale sources…) plus
schema-refinement suggestions.
- `confidence_threshold` (default 0.5) — min confidence to report.

### `wiki_graph_stats`
No args. Returns vertex/edge counts (entities, facts, schemas, passages).

### `wiki_resolve_conflicts`
No args. Lists fact contradictions — facts sharing `(head, relation)` but different
`tail`. Use when reconciling conflicting information.

## Rules & etiquette

- **Cite.** Always surface the `citations`/`slug`s behind a claim; never launder wiki
  content as your own recall.
- **Search before you ingest** to keep the wiki free of duplicates.
- **Respect the schema.** The seat's `schema/AGENTS.md` governs allowed categories,
  off-limits topics, and honesty rules; ingest enforces them. If a category is
  refused, it's off-limits — don't retry with a workaround.
- **EU data residency + Hermes-only LLM.** All judgment (summarize/answer/extract)
  routes through the seat's configured model. If `degraded: true`, the model path is
  down — retrieval still works structurally, but flag reduced confidence.
- **Prefer the cheap tool.** Reach for `wiki_context`/`wiki_search` before
  `wiki_query`; only pay for synthesis when you actually need it.
