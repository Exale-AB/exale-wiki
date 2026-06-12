"""Chunking: heading splits, token budget, content preservation (T08)."""

from wiki_engine.chunk import chunk_page


def test_short_page_is_a_single_chunk():
    chunks = chunk_page("p", "Just one short line of text.")
    assert len(chunks) == 1
    assert chunks[0].slug == "p"
    assert chunks[0].text == "Just one short line of text."


def test_splits_on_markdown_headings():
    body = "Intro paragraph.\n\n# Section A\nAlpha body.\n\n## Section B\nBravo body."
    chunks = chunk_page("p", body)

    headings = [c.heading for c in chunks]
    assert "# Section A" in headings
    assert "## Section B" in headings
    # The preamble before the first heading is its own (heading-less) chunk.
    assert any(c.heading == "" and "Intro paragraph." in c.text for c in chunks)


def test_respects_max_tokens_budget():
    para1 = "x" * 40
    para2 = "y" * 40
    body = f"{para1}\n\n{para2}"  # 2 paragraphs, 40 chars each

    chunks = chunk_page("p", body, max_tokens=12)  # 12*4 = 48 char budget

    # Each chunk stays under budget; the two 40-char paragraphs can't co-pack.
    assert all(len(c.text) <= 48 for c in chunks)
    assert len(chunks) == 2


def test_oversized_paragraph_is_hard_split():
    body = "z" * 100
    chunks = chunk_page("p", body, max_tokens=10)  # 40-char budget

    assert all(len(c.text) <= 40 for c in chunks)
    assert "".join(c.text for c in chunks) == body
