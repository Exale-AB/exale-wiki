from wiki_engine.fakes import FakeAnswerer, FakeEmbedder, FakeSummarizer
from wiki_engine.protocols import Summarizer
from wiki_engine.source import Source, SourceKind


def _source(text: str = "First line.\nSecond line.") -> Source:
    return Source(kind=SourceKind.FILE, identifier="f1", text=text, title="Doc One")


def test_fake_summarizer_satisfies_protocol():
    summarizer: Summarizer = FakeSummarizer()
    assert isinstance(summarizer.summarize(_source()), str)


def test_fake_summary_is_deterministic_and_uses_first_line():
    out = FakeSummarizer().summarize(_source())
    assert out == FakeSummarizer().summarize(_source())
    assert "Doc One" in out
    assert "First line." in out
    assert "Second line." not in out


def test_fake_summary_truncates_long_first_line():
    long = "x" * 500
    out = FakeSummarizer().summarize(_source(text=long))
    assert len(out) < 300


def test_fake_embedder_is_deterministic_and_fixed_dim():
    emb = FakeEmbedder(dim=8)
    a = emb.embed(["acme renewal contract"])
    b = emb.embed(["acme renewal contract"])
    assert a == b
    assert len(a) == 1 and len(a[0]) == 8


def test_fake_embedder_shared_words_increase_similarity():
    from wiki_engine.retrieval import cosine

    emb = FakeEmbedder(dim=32)
    [q] = emb.embed(["kubernetes deployment"])
    [near] = emb.embed(["kubernetes deployment guide"])
    [far] = emb.embed(["marketing newsletter copy"])
    assert cosine(q, near) > cosine(q, far)


def test_fake_embedder_embeds_each_text_independently():
    emb = FakeEmbedder(dim=8)
    out = emb.embed(["one", "two", "three"])
    assert len(out) == 3


def test_fake_answerer_uses_question_and_context():
    answer = FakeAnswerer().answer("What is the renewal date?", ["page A body", "page B body"])
    assert "renewal" in answer.lower()
    assert "page A body" in answer
