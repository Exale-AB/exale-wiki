from wiki_engine.protocols import Answerer, Embedder, Summarizer


def test_protocols_are_runtime_importable():
    # The protocols are structural; just assert the names exist and are distinct.
    assert Summarizer is not Embedder
    assert Embedder is not Answerer
    assert {Summarizer, Embedder, Answerer}  # all hashable/usable


def test_embedder_structural_conformance():
    class Impl:
        def embed(self, texts):
            return [[0.0] for _ in texts]

    embedder: Embedder = Impl()
    assert embedder.embed(["a", "b"]) == [[0.0], [0.0]]


def test_answerer_structural_conformance():
    class Impl:
        def answer(self, question, context):
            return f"{question}:{len(list(context))}"

    answerer: Answerer = Impl()
    assert answerer.answer("q", ["c1", "c2"]) == "q:2"
