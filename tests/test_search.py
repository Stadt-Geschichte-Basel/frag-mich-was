"""Tests for lexical ranking, Reciprocal Rank Fusion, and the search modes."""

import asyncio
import json
import re
import threading
import tomllib
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest

from app import (
    DEFAULT_MODE_LABEL,
    MODES,
    RRF_K,
    TOP_K,
    Chunk,
    Mode,
    ModelInfo,
    best_per_publication,
    build_lexical_index,
    fuse,
    lexical_rank,
    lexical_tokens,
    load_embedder,
    load_index,
    query_vector,
    rank,
    search,
    vector_for,
)
from scripts.build_index import FIXTURE_FILE, INDEX_FILE

ROOT = Path(__file__).resolve().parents[1]


def make(id: str, *, title: str = "Titel", text: str = "Text", url: str | None = None) -> Chunk:
    return Chunk(id=id, title=title, text=text, source=f"{id}.md", url=url, embedding=[1.0])


def ids(results: list[tuple[Chunk, float]]) -> list[str]:
    return [chunk.id for chunk, _ in results]


def test_tokens_lowercase_drop_stopwords_and_keep_names_and_dates() -> None:
    assert lexical_tokens(["Die Zünfte der Stadt BASEL im Jahr 1501"]) == [
        ["zünfte", "stadt", "basel", "jahr", "1501"]
    ]


def test_no_stemming() -> None:
    """A word form matches only itself."""
    assert lexical_tokens(["Handel Handelsstadt Händler"]) == [
        ["handel", "handelsstadt", "händler"]
    ]


def test_title_text_and_query_use_the_same_tokens() -> None:
    chunks = [
        make("a", title="Rhein", text="Zunft"),
        make("b", title="Aare", text="Rhein"),
        make("c", title="Aare", text="Birs"),
    ]
    index = build_lexical_index(chunks)
    assert ids(lexical_rank(index, "RHEIN")) == ["a", "b"]
    assert ids(lexical_rank(index, "zunft")) == ["a"]
    assert ids(lexical_rank(index, "  Birs. ")) == ["c"]


@pytest.mark.parametrize("query", ["", "   ", "der die das und", "xyzzyqq", "?!"])
def test_no_lexical_match(query: str) -> None:
    """An empty, stopword-only, unknown, or symbol-only query returns nothing."""
    index = build_lexical_index([make("a", title="Rhein", text="Handel")])
    assert lexical_rank(index, query) == []


def test_known_and_unknown_words_in_one_query() -> None:
    index = build_lexical_index([make("a", title="Rhein", text="Handel"), make("b")])
    assert ids(lexical_rank(index, "Rhein xyzzyqq")) == ["a"]


def test_lexical_rank_skips_scores_of_zero_or_less() -> None:
    chunks = [make("a", title="Rhein"), make("b", title="Aare"), make("c", title="Birs")]
    results = lexical_rank(build_lexical_index(chunks), "Rhein")
    assert ids(results) == ["a"]
    assert all(score > 0 for _, score in results)


def test_lexical_rank_keeps_the_best_passage_of_each_publication() -> None:
    chunks = [
        make("a", text="Rhein", url="docs/one.html"),
        make("b", text="Rhein Rhein Rhein Handel Zunft", url="docs/one.html"),
        make("c", text="Rhein", url="docs/two.html"),
        make("d", text="Rhein"),
        make("e", text="Rhein"),
    ]
    index = build_lexical_index(chunks)
    results = lexical_rank(index, "Rhein", None)
    assert len(results) == 4  # Two passages share one URL. A passage without a URL stands alone.
    assert [chunk.url or chunk.id for chunk, _ in results].count("docs/one.html") == 1
    assert "d" in ids(results) and "e" in ids(results)


def test_lexical_rank_breaks_score_ties_by_passage_id() -> None:
    chunks = [make(name, text="Rhein") for name in ("c", "a", "b")]
    assert ids(lexical_rank(build_lexical_index(chunks), "Rhein")) == ["a", "b", "c"]


def test_lexical_rank_limit() -> None:
    chunks = [make(f"p{number}", text="Rhein") for number in range(8)]
    index = build_lexical_index(chunks)
    assert len(lexical_rank(index, "Rhein")) == TOP_K
    assert len(lexical_rank(index, "Rhein", 2)) == 2
    assert len(lexical_rank(index, "Rhein", None)) == 8


def test_indexing_and_search_start_no_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pyodide has no threads. The lexical path must not start one."""

    def forbidden(self: threading.Thread) -> None:
        raise AssertionError("a thread started")

    monkeypatch.setattr(threading.Thread, "start", forbidden)
    index = build_lexical_index([make("a", text="Rhein"), make("b", text="Aare")])
    assert ids(search("lexical", "Rhein", None, index)) == ["a"]
    assert ids(lexical_rank(index, "Rhein", None)) == ["a"]


def test_best_per_publication_uses_url_or_id() -> None:
    a = make("a", url="docs/x.html")
    b = make("b", url="docs/x.html")
    c = make("c")
    assert ids(best_per_publication([(b, 1.0), (a, 1.0), (c, 1.0)])) == ["a", "c"]
    assert ids(best_per_publication([(a, 1.0), (b, 2.0), (c, 0.5)])) == ["b", "c"]


def test_rank_returns_every_publication_without_a_limit() -> None:
    chunks = [make(f"p{number}") for number in range(9)]
    assert len(rank([1.0], chunks)) == TOP_K
    assert len(rank([1.0], chunks, None)) == 9


def test_fuse_scores_with_one_based_ranks_and_the_fixed_formula() -> None:
    a, b, c = make("a"), make("b"), make("c")
    fused = fuse([(a, 0.9), (b, 0.8), (c, 0.7)], [(c, 5.0), (a, 4.0)])
    assert RRF_K == 60
    assert [(chunk.id, score) for chunk, score in fused] == [
        ("a", 1 / 61 + 1 / 62),
        ("c", 1 / 63 + 1 / 61),
        ("b", 1 / 62),
    ]


def test_fuse_keeps_publications_from_one_ranking_only() -> None:
    a, b = make("a"), make("b")
    assert ids(fuse([(a, 1.0)], [(b, 1.0)])) == ["a", "b"]
    assert ids(fuse([(a, 1.0)], [])) == ["a"]
    assert ids(fuse([], [(b, 1.0)])) == ["b"]
    assert fuse([], []) == []


def test_fuse_takes_the_passage_from_the_better_rank() -> None:
    url = "docs/x.html"
    semantic_passage, lexical_passage = make("s", url=url), make("l", url=url)
    other = make("o")
    # The lexical rank is better: the lexical passage wins.
    fused = fuse([(other, 1.0), (semantic_passage, 0.5)], [(lexical_passage, 3.0)])
    assert ids(fused) == ["l", "o"]
    # The semantic rank is better: the semantic passage wins.
    fused = fuse([(semantic_passage, 1.0)], [(other, 3.0), (lexical_passage, 2.0)])
    assert ids(fused) == ["s", "o"]


def test_fuse_takes_the_semantic_passage_when_both_ranks_match() -> None:
    url = "docs/x.html"
    semantic_passage, lexical_passage = make("z", url=url), make("a", url=url)
    assert ids(fuse([(semantic_passage, 1.0)], [(lexical_passage, 3.0)])) == ["z"]


def test_fuse_breaks_score_ties_by_passage_id() -> None:
    """The top semantic-only and the top lexical-only publication score the same."""
    low, high = make("a"), make("b")
    assert ids(fuse([(high, 1.0)], [(low, 1.0)])) == ["a", "b"]
    assert ids(fuse([(low, 1.0)], [(high, 1.0)])) == ["a", "b"]


def test_fuse_applies_the_limit_after_combination() -> None:
    """A publication below the semantic top five can win through its lexical rank."""
    semantic = [(make(f"s{number}"), 1.0 - number / 10) for number in range(1, 7)]
    late = semantic[-1][0]
    fused = fuse(semantic, [(late, 9.0)])
    assert len(fused) == TOP_K
    assert fused[0][0] is late
    assert len(fuse(semantic, [(late, 9.0)], None)) == 6


def test_search_modes() -> None:
    chunks = [
        make("a", title="Rhein", text="Fischerei"),
        make("b", title="Aare", text="Handel"),
    ]
    index = build_lexical_index(chunks)
    assert MODES == {"Kombiniert": "combined", "Lexikalisch": "lexical", "Semantisch": "semantic"}
    assert MODES[DEFAULT_MODE_LABEL] == "semantic"
    assert ids(search("lexical", "Fischerei", None, index)) == ["a"]
    assert ids(search("lexical", "unbekannt", [1.0], index)) == []
    assert ids(search("semantic", "Fischerei", [1.0], index)) == ["a", "b"]
    assert ids(search("combined", "Fischerei", [1.0], index)) == ["a", "b"]
    # Without the vector, the combined mode falls back to the lexical ranking.
    assert ids(search("combined", "Fischerei", None, index)) == ["a"]
    with pytest.raises(ValueError, match="semantic mode needs a query vector"):
        search("semantic", "Fischerei", None, index)


# The browser orchestration, with a fake model in place of the browser.


class FakeVector:
    """Stand in for the JavaScript array that Pyodide returns."""

    def __init__(self, values: list[float]) -> None:
        self.values = values

    def to_py(self) -> list[float]:
        return list(self.values)


class FakeModel:
    """Count the loads and the embedded texts. Return a fixed vector."""

    def __init__(self, vector: list[float] | None = None, fails: bool = False) -> None:
        self.vector = vector or [1.0, 0.0]
        self.fails = fails
        self.loads = 0
        self.texts: list[str] = []

    async def load(self, model: ModelInfo) -> Callable[[str], Awaitable[FakeVector]]:
        self.loads += 1
        if self.fails:
            raise RuntimeError("offline")

        async def embed(text: str) -> FakeVector:
            self.texts.append(text)
            return FakeVector(self.vector)

        return embed


MODEL_INFO = ModelInfo(
    document_model="a",
    document_revision="1",
    query_model="b",
    query_revision="2",
    dimensions=2,
    query_prefix="query: ",
)


def test_query_vector_loads_the_model_once_and_adds_the_prefix() -> None:
    fake, session = FakeModel(), {}
    assert asyncio.run(query_vector(session, MODEL_INFO, "Rhein", fake.load)) == [1.0, 0.0]
    assert asyncio.run(query_vector(session, MODEL_INFO, "Aare", fake.load)) == [1.0, 0.0]
    assert fake.loads == 1
    assert fake.texts == ["query: Rhein", "query: Aare"]
    assert (session["query"], session["vector"]) == ("Aare", [1.0, 0.0])


def test_query_vector_reuses_the_vector_of_the_last_successful_query() -> None:
    """A change of mode runs the search again with the same query. It must not embed again."""
    fake, session = FakeModel(), {}
    asyncio.run(query_vector(session, MODEL_INFO, "Rhein", fake.load))
    asyncio.run(query_vector(session, MODEL_INFO, "Rhein", fake.load))
    assert fake.texts == ["query: Rhein"]


def test_query_vector_failure_keeps_the_last_successful_query() -> None:
    fake, session = FakeModel(), {}
    asyncio.run(query_vector(session, MODEL_INFO, "Rhein", fake.load))
    fake.vector = [3.0, 4.0]  # A vector without unit length is not valid.
    with pytest.raises(ValueError, match="norm"):
        asyncio.run(query_vector(session, MODEL_INFO, "Aare", fake.load))
    assert (session["query"], session["vector"]) == ("Rhein", [1.0, 0.0])
    offline, empty = FakeModel(fails=True), {}
    with pytest.raises(RuntimeError, match="offline"):
        asyncio.run(query_vector(empty, MODEL_INFO, "Rhein", offline.load))
    assert empty == {}


def test_vector_for_needs_no_model_in_lexical_mode() -> None:
    fake = FakeModel()
    assert asyncio.run(vector_for("lexical", "Rhein", {}, MODEL_INFO, fake.load)) is None
    assert fake.loads == 0 and fake.texts == []


@pytest.mark.parametrize("mode", ["semantic", "combined"])
def test_vector_for_returns_the_vector_or_none_when_the_model_fails(mode: Mode) -> None:
    assert asyncio.run(vector_for(mode, "Rhein", {}, MODEL_INFO, FakeModel().load)) == [1.0, 0.0]
    offline = FakeModel(fails=True)
    assert asyncio.run(vector_for(mode, "Rhein", {}, MODEL_INFO, offline.load)) is None
    wrong = FakeModel(vector=[3.0, 4.0])
    assert asyncio.run(vector_for(mode, "Rhein", {}, MODEL_INFO, wrong.load)) is None


def test_the_browser_model_does_not_load_outside_the_browser() -> None:
    with pytest.raises(RuntimeError, match="WebAssembly"):
        asyncio.run(load_embedder(MODEL_INFO))


# The committed index and the reference vectors.

INDEX = load_index(INDEX_FILE.read_text(encoding="utf-8"))
FIXTURE = json.loads(FIXTURE_FILE.read_text(encoding="utf-8"))
LEXICAL = build_lexical_index(INDEX.chunks)


def distinct_publications(results: list[tuple[Chunk, float]]) -> bool:
    keys = [chunk.url or chunk.id for chunk, _ in results]
    return len(keys) == len(set(keys))


@pytest.mark.parametrize(("query", "word"), [("Merian", "merian"), ("1501", "1501")])
def test_name_and_date_queries_find_passages_with_the_word(query: str, word: str) -> None:
    results = search("lexical", query, None, LEXICAL)
    assert 1 <= len(results) <= TOP_K
    assert distinct_publications(results)
    for chunk, score in results:
        assert score > 0
        assert word in lexical_tokens([f"{chunk.title}\n{chunk.text}"])[0]


def test_unknown_word_finds_no_passage_in_the_index() -> None:
    assert search("lexical", "xyzzyqq", None, LEXICAL) == []


def test_semantic_mode_keeps_the_reference_result() -> None:
    reference = FIXTURE["reference"]
    results = search("semantic", reference["query"], reference["embedding"], LEXICAL)
    assert ids(results) == ids(rank(reference["embedding"], INDEX.chunks))
    assert reference["expected_url"] in [chunk.url for chunk, _ in results][:3]


def test_combined_mode_finds_the_reference_publications() -> None:
    references = [FIXTURE["reference"], *FIXTURE["story_references"]]
    for item in references:
        results = search("combined", item["query"], item["embedding"], LEXICAL)
        assert 1 <= len(results) <= TOP_K, item["query"]
        assert distinct_publications(results), item["query"]
        assert item["expected_url"] in [chunk.url for chunk, _ in results][:3], item["query"]


def test_browser_pin_matches_the_project_pin() -> None:
    """The WebAssembly export reads the pin from the notebook header, not from pyproject.toml."""
    header = re.search(r'#\s+"bm25s==([^"]+)"', (ROOT / "app.py").read_text(encoding="utf-8"))
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert header is not None
    assert f"bm25s=={header.group(1)}" in project["project"]["dependencies"]
