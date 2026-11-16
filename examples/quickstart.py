"""Ingest, query and lint a tiny wiki. No API keys, no database.

The judgment steps (summarise, embed, answer) use the deterministic fakes the
engine ships for tests, so this runs offline. Swap them for real backends when
you wire the engine to a model — see the README.

Run from an empty directory that is a git repo:

    git init my-wiki && python examples/quickstart.py my-wiki
"""

import sys
from pathlib import Path

from wiki_engine import (
    FakeAnswerer,
    FakeEmbedder,
    FakeSummarizer,
    InMemoryVectorStore,
    Retriever,
    Source,
    SourceKind,
    WikiRepo,
    WikiSchema,
    ingest,
    lint,
    query,
)


def main(root: Path) -> None:
    repo = WikiRepo.init(root)  # creates raw/, wiki/ and schema/
    schema = WikiSchema()  # the default rulebook
    embedder, store = FakeEmbedder(), InMemoryVectorStore()

    # 1. Ingest: a source becomes a cited wiki page and a git commit.
    ingest(
        Source(
            SourceKind.MESSAGE,
            "slack:42",
            "Acme renewal is due 1 March. Contact: Dana Berg.",
            "Acme renewal",
        ),
        repo=repo,
        schema=schema,
        summarizer=FakeSummarizer(),
        embedder=embedder,
        store=store,
    )

    # 2. Query: get the relevant pages back as raw context, with citations.
    retriever = Retriever(repo=repo, store=store, embedder=embedder)
    answer = query(
        "When is the Acme renewal?",
        retriever=retriever,
        answerer=FakeAnswerer(),
        repo=repo,
    )
    print(answer.text)
    print("cited:", answer.citations)

    # 3. Lint: ask the wiki to check itself. An empty list means it is healthy.
    print("lint:", lint(repo, schema))


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("my-wiki"))
