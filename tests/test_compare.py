"""Tests for the mode comparison, its summary, and the comparison notebook."""

import json
import math
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

from app import (
    TOP_K,
    Chunk,
    build_lexical_index,
    check_vector,
    load_index,
    search,
)
from compare import app as compare_app
from scripts.build_index import FIXTURE_FILE, INDEX_FILE, MODEL, embed, load_encoder
from scripts.compare_modes import (
    EXPECTED_TOP,
    MODE_NAMES,
    Comparison,
    ExampleResult,
    RankRow,
    compare,
    comparison_items,
    evaluate_example,
    load_comparison,
    main,
    position,
    publication,
    summary_rows,
)
from scripts.comparison_queries import KINDS, QUERY_EXAMPLES, QueryKind

ROOT = Path(__file__).resolve().parents[1]


def make(id: str, *, title: str = "Titel", text: str = "Text", url: str | None = None) -> Chunk:
    return Chunk(id=id, title=title, text=text, source=f"{id}.md", url=url, embedding=[1.0])


def ids(results: list[tuple[Chunk, float]]) -> list[str]:
    return [chunk.id for chunk, _ in results]


# Small synthetic cases.


def test_missing_publication_has_no_rank() -> None:
    """A mode that skips a publication gives ``None``. It never gives rank 0."""
    a, b = make("a"), make("b")
    comparison = Comparison("q", [(a, 1.0), (b, 0.5)], [(b, 2.0)], [(b, 0.1)])
    assert position(comparison, "semantic", "b") == 2
    assert position(comparison, "lexical", "a") is None
    assert position(comparison, "combined", "a") is None


def test_position_uses_the_publication_key() -> None:
    first, second = make("a", url="docs/x.html"), make("b", url="docs/x.html")
    comparison = Comparison("q", [(first, 1.0)], [(second, 1.0)], [])
    assert publication(first) == publication(second) == "docs/x.html"
    assert position(comparison, "lexical", "docs/x.html") == 1


# The committed index and the reference vectors.

INDEX = load_index(INDEX_FILE.read_text(encoding="utf-8"))
FIXTURE = json.loads(FIXTURE_FILE.read_text(encoding="utf-8"))
LEXICAL = build_lexical_index(INDEX.chunks)
ALL_ITEMS = comparison_items(FIXTURE)
# The chapter query and the story queries come first.
REFERENCES = [FIXTURE["reference"], *FIXTURE["story_references"]]


@pytest.mark.parametrize("item", ALL_ITEMS, ids=lambda item: item["query"][:30])
def test_comparison_agrees_with_the_search_modes(item: dict) -> None:
    """The comparison and the page rank alike, so that the notebook shows what users get."""
    comparison = compare(item["query"], item["embedding"], LEXICAL)
    for mode in MODE_NAMES:
        vector = None if mode == "lexical" else item["embedding"]
        shown = ids(search(mode, item["query"], vector, LEXICAL))
        assert ids(comparison.ranking(mode)[:TOP_K]) == shown, mode


@pytest.mark.parametrize("item", ALL_ITEMS, ids=lambda item: item["query"][:30])
def test_each_ranking_is_complete_and_distinct(item: dict) -> None:
    comparison = compare(item["query"], item["embedding"], LEXICAL)
    publications = {publication(chunk) for chunk in INDEX.chunks}
    assert len(comparison.semantic) == len(publications)
    for mode in MODE_NAMES:
        keys = [publication(chunk) for chunk, _ in comparison.ranking(mode)]
        assert len(keys) == len(set(keys))
        assert set(keys) <= publications
    # The combined ranking keeps each publication that any ranking has.
    assert {publication(chunk) for chunk, _ in comparison.combined} == {
        publication(chunk) for chunk, _ in [*comparison.semantic, *comparison.lexical]
    }


def test_the_combined_mode_passes_every_reference_query() -> None:
    """The combined ranking must not lose a reference publication that one mode finds."""
    for item in ALL_ITEMS[: len(REFERENCES)]:
        assert evaluate_example(item, LEXICAL).all_found("combined"), item["query"]


def test_main_prints_the_summary(capsys: pytest.CaptureFixture[str]) -> None:
    main()
    output = capsys.readouterr().out
    assert output.startswith("| Type | Mode |")
    assert len(output.split("\n\n")[0].splitlines()) == 2 + 3 * (1 + len(KINDS))
    assert "| all | combined | 44 | 38 | 41 |" in output
    assert f"top {EXPECTED_TOP}" not in output and f"is {EXPECTED_TOP} or 5" in output


# The notebook.


def test_notebook_runs_and_shows_the_reference_results() -> None:
    outputs, defs = compare_app.run()
    assert {query.query for query in defs["report"].queries} == {
        item["query"] for item in ALL_ITEMS
    }
    assert defs["kind_filter"].value == "all"
    assert defs["filtered"] == defs["report"].queries
    assert defs["picker"].value == 0
    texts = [getattr(output, "text", "") for output in outputs]
    assert any(defs["filtered"][0].query in text for text in texts)
    assert any("Was der Vergleich zeigt" in text for text in texts)


def test_notebook_passes_the_marimo_check() -> None:
    check = subprocess.run(
        [sys.executable, "-m", "marimo", "check", "compare.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert check.returncode == 0, check.stdout + check.stderr


# Expanded examples and measurements. Their retrieval quality is measured, not asserted.


def test_catalogue_covers_all_volumes_and_stories_with_source_evidence() -> None:
    assert len(ALL_ITEMS) == 44
    assert len({item["query"] for item in ALL_ITEMS}) == 44
    assert Counter(case.kind for case in QUERY_EXAMPLES) == {
        "specific": 16,
        "synonyms": 8,
        "complex": 8,
        "cross-source": 4,
    }
    sources = {chunk.source: chunk.url for chunk in INDEX.chunks}
    covered = {source for case in QUERY_EXAMPLES for source, _ in case.evidence}
    assert {source[4:6] for source in covered if source.startswith("sgb-")} == {
        f"{number:02d}" for number in range(1, 10)
    }
    assert len([source for source in covered if source.startswith("data-story-")]) == 7
    for case in QUERY_EXAMPLES:
        assert len(case.expected_urls) == (2 if case.kind == "cross-source" else 1)
        assert len(set(case.expected_urls)) == len(case.expected_urls)
        assert tuple(sources[source] for source, _ in case.evidence) == case.expected_urls
        for source, note in case.evidence:
            assert note in (ROOT / "content" / source).read_text(encoding="utf-8")


def test_generated_examples_match_the_catalogue_and_have_valid_vectors() -> None:
    for item, case in zip(FIXTURE["comparison_references"], QUERY_EXAMPLES, strict=True):
        assert (item["query"], item["topic"], item["kind"], tuple(item["expected_urls"])) == (
            case.query,
            case.topic,
            case.kind,
            case.expected_urls,
        )
        check_vector(item["embedding"], MODEL.dimensions)


def synthetic_result(kind: QueryKind = "cross-source") -> ExampleResult:
    return ExampleResult(
        Comparison("q", [], [], []),
        "Topic",
        kind,
        (RankRow("A", "a", 1, None, 1), RankRow("B", "b", 4, None, 6)),
    )


def test_complete_retrieval_needs_every_expected_source() -> None:
    result = synthetic_result()
    assert not result.all_found("semantic", 3)
    assert result.all_found("semantic", 5)
    assert not result.all_found("lexical", 5)
    assert not result.all_found("combined", 5)
    assert not result.all_found("semantic", 0)


def test_summary_counts_complete_queries_by_type_and_mode() -> None:
    multi = synthetic_result()
    single = ExampleResult(multi.comparison, "Other", "specific", multi.expected[:1])
    rows = summary_rows([single, multi])
    assert [row for row in rows if row["kind"] == "all" and row["mode"] == "semantic"] == [
        {"kind": "all", "mode": "semantic", "queries": 2, "complete3": 1, "complete5": 2}
    ]
    assert {row["kind"] for row in rows} == {"all", "specific", "cross-source"}
    assert [row["kind"] for row in rows[:3]] == ["all"] * 3
    assert summary_rows([]) == []


def test_evaluator_records_missing_and_skipped_sources_without_passing() -> None:
    lexical = build_lexical_index([make("a", title="Rhein", text="Rhein", url="u")])
    item = {
        "query": "xyzzy",
        "embedding": [1.0],
        "expected_urls": ["u", "absent"],
        "topic": "Topic",
        "kind": "cross-source",
    }
    result = evaluate_example(item, lexical)
    assert result.expected == (
        RankRow("Rhein", "u", 1, None, 1),
        RankRow("absent", "absent", None, None, None),
    )
    assert not result.all_found("semantic")
    assert not result.all_found("combined")


@pytest.mark.parametrize("keys", [[], ["u", "u"]])
def test_evaluator_rejects_empty_or_duplicate_expected_sources(keys: list[str]) -> None:
    with pytest.raises(ValueError, match="nonempty and distinct"):
        evaluate_example({"expected_urls": keys}, LEXICAL)


def test_load_comparison_matches_the_saved_examples() -> None:
    lexical, items = load_comparison()
    assert len(lexical.chunks) == len(INDEX.chunks)
    assert items == ALL_ITEMS
    assert {item["expected_url"] for item in items[: len(REFERENCES)]} == {
        item["expected_url"] for item in REFERENCES
    }
    assert {item["kind"] for item in items} == set(KINDS)


def test_python_model_reproduces_all_expanded_query_vectors() -> None:
    pytest.importorskip("sentence_transformers")
    vectors = embed(load_encoder(), [MODEL.query_prefix + case.query for case in QUERY_EXAMPLES])
    for vector, item in zip(vectors, FIXTURE["comparison_references"], strict=True):
        assert math.sumprod(vector, item["embedding"]) > 0.999, item["query"]


def test_notebook_shows_both_expected_links_for_a_cross_source_query() -> None:
    from types import SimpleNamespace

    from scripts.comparison_report import build_report

    query = build_report().queries[-1]
    outputs, defs = compare_app.run(defs={"filtered": [query], "picker": SimpleNamespace(value=0)})
    texts = [getattr(output, "text", "") for output in outputs]
    assert any("Erwartete Publikationen" in text for text in texts)
    assert len(query.expected) == 2
    for row in query.expected:
        assert any(row.key in text for text in texts)
    assert defs["filtered"] == [query]


def test_notebook_filters_by_type() -> None:
    from types import SimpleNamespace

    _outputs, defs = compare_app.run(defs={"kind_filter": SimpleNamespace(value="synonyms")})
    assert defs["filtered"]
    assert {query.kind for query in defs["filtered"]} == {"synonyms"}
