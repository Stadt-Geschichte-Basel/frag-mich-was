"""Tests for the mode comparison, the reference table, and the comparison notebook."""

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
from scripts.build_index import (
    FIXTURE_FILE,
    INDEX_FILE,
    MODEL,
    REFERENCE_QUERY,
    embed,
    load_encoder,
)
from scripts.compare_modes import (
    EXPECTED_TOP,
    MODE_NAMES,
    Comparison,
    ExampleResult,
    RankRow,
    ReferenceResult,
    compare,
    comparison_items,
    evaluate,
    evaluate_example,
    example_rows,
    filter_examples,
    format_rank,
    lexical_excerpts,
    load_comparison,
    load_reference,
    main,
    markdown_table,
    overlap,
    pass_counts,
    position,
    publication,
    rank_table,
    reference_items,
    reference_table,
    summary_rows,
    top_keys,
)
from scripts.comparison_queries import KIND_NAMES, QUERY_EXAMPLES

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
    assert format_rank(position(comparison, "lexical", "a")) == "—"


def test_position_uses_the_publication_key() -> None:
    first, second = make("a", url="docs/x.html"), make("b", url="docs/x.html")
    comparison = Comparison("q", [(first, 1.0)], [(second, 1.0)], [])
    assert publication(first) == publication(second) == "docs/x.html"
    assert position(comparison, "lexical", "docs/x.html") == 1


def test_top_keys_and_overlap_respect_the_limit() -> None:
    chunks = [make(f"p{number}") for number in range(6)]
    semantic = [(chunk, 1.0) for chunk in chunks]
    lexical = [(chunk, 1.0) for chunk in reversed(chunks)]
    comparison = Comparison("q", semantic, lexical, semantic)
    assert top_keys(comparison, "semantic") == [f"p{number}" for number in range(TOP_K)]
    # The semantic top five is p0 to p4. The lexical top five is p5 to p1. They share p1 to p4.
    assert overlap(comparison, "semantic", "lexical") == 4
    assert overlap(comparison, "semantic", "semantic") == TOP_K
    assert overlap(comparison, "semantic", "lexical", 6) == 6


def test_lexical_excerpts_count_passages_from_the_lexical_ranking() -> None:
    url = "docs/x.html"
    semantic_passage, lexical_passage = make("s", url=url), make("l", url=url)
    other = make("o")
    semantic = [(semantic_passage, 1.0), (other, 0.5)]
    combined = [(lexical_passage, 0.1), (other, 0.05)]
    comparison = Comparison("q", semantic, [(lexical_passage, 1.0)], combined)
    assert lexical_excerpts(comparison) == 1
    assert lexical_excerpts(comparison, 0) == 0


def test_rank_table_lists_the_union_with_ranks_in_each_mode() -> None:
    a, b, c = make("a"), make("b"), make("c")
    comparison = Comparison(
        "q",
        [(a, 1.0), (b, 0.9), (c, 0.8)],
        [(c, 3.0)],
        [(c, 0.04), (a, 0.03), (b, 0.02)],
    )
    rows = rank_table(comparison, 1)
    assert rows == [
        RankRow("Titel", "c", 3, 1, 1),
        RankRow("Titel", "a", 1, None, 2),
    ]
    assert [row.key for row in rank_table(comparison, 3)] == ["c", "a", "b"]


def test_rank_table_puts_a_publication_that_combined_skips_last() -> None:
    a, b = make("a"), make("b")
    comparison = Comparison("q", [(a, 1.0)], [(b, 1.0)], [(a, 0.1)])
    assert [(row.key, row.combined) for row in rank_table(comparison)] == [("a", 1), ("b", None)]


def test_reference_result_passes_only_inside_the_expected_top() -> None:
    result = ReferenceResult("q", "u", EXPECTED_TOP, EXPECTED_TOP + 1, None, 0, 0, 0)
    assert result.passes("semantic")
    assert not result.passes("lexical")
    assert not result.passes("combined")
    assert pass_counts([result, result]) == {"semantic": 2, "lexical": 0, "combined": 0}


def test_reference_table_has_one_row_for_each_result() -> None:
    result = ReferenceResult("Frage?", "u", 1, None, 2, 3, 1, 0)
    lines = reference_table([result, result]).splitlines()
    assert len(lines) == 4
    assert lines[2] == "| Frage? | 1 | — | 2 | 3 | 1 | 0 |"


# The committed index and the reference vectors.

INDEX = load_index(INDEX_FILE.read_text(encoding="utf-8"))
FIXTURE = json.loads(FIXTURE_FILE.read_text(encoding="utf-8"))
LEXICAL = build_lexical_index(INDEX.chunks)
ITEMS = reference_items(FIXTURE)
ALL_ITEMS = comparison_items(FIXTURE)


def test_reference_items_cover_the_chapter_and_the_story_queries() -> None:
    assert [item["query"] for item in ITEMS][0] == REFERENCE_QUERY
    assert len(ITEMS) == 1 + len(FIXTURE["story_references"])


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


@pytest.mark.parametrize("item", ALL_ITEMS, ids=lambda item: item["query"][:30])
def test_rank_table_matches_each_mode(item: dict) -> None:
    comparison = compare(item["query"], item["embedding"], LEXICAL)
    rows = rank_table(comparison)
    shown = {key for mode in MODE_NAMES for key in top_keys(comparison, mode)}
    assert {row.key for row in rows} == shown
    for row in rows:
        for mode in MODE_NAMES:
            assert getattr(row, mode) == position(comparison, mode, row.key)


def test_evaluate_reports_the_expected_publication() -> None:
    result = evaluate(ITEMS[0], LEXICAL)
    assert result.expected_url == ITEMS[0]["expected_url"]
    assert result.passes("semantic") and result.passes("combined")
    assert 0 <= result.lexical_excerpts <= TOP_K
    assert 0 <= result.combined_with_semantic <= TOP_K
    assert 0 <= result.combined_with_lexical <= TOP_K


def test_the_combined_mode_passes_every_reference_query() -> None:
    """The combined ranking must not lose a reference publication that one mode finds."""
    for item in ITEMS:
        result = evaluate(item, LEXICAL)
        assert result.passes("combined"), item["query"]


def test_main_prints_the_table(capsys: pytest.CaptureFixture[str]) -> None:
    main()
    output = capsys.readouterr().out
    assert output.startswith("| Query |")
    query_table, rest = output.split("\n\n", 1)
    assert len(query_table.splitlines()) == len(ALL_ITEMS) + 2
    assert "Coverage@3" in rest and "All found@5" in rest
    assert "Cross-source" in rest
    assert f"top {EXPECTED_TOP}" in output


def test_load_reference_matches_the_committed_files() -> None:
    lexical, items = load_reference()
    assert len(lexical.chunks) == len(INDEX.chunks)
    assert items == ITEMS


# The notebook.


def test_notebook_runs_and_shows_the_reference_results() -> None:
    _outputs, defs = compare_app.run()
    assert {query.query for query in defs["report"].queries} == {
        item["query"] for item in ALL_ITEMS
    }
    assert defs["selected"] == defs["report"].queries[0]
    assert defs["kind_filter"].value == defs["topic_filter"].value == "all"
    assert not defs["misses_only"].value
    assert "encoder" not in defs["cache"]


def test_notebook_passes_the_marimo_check() -> None:
    check = subprocess.run(
        [sys.executable, "-m", "marimo", "check", "compare.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert check.returncode == 0, check.stdout + check.stderr


def test_free_query_encoder_reproduces_the_reference_vector() -> None:
    """The notebook embeds a free query with the build code. It must match the fixture.

    This test needs the ``index`` dependency group. Without the group, pytest skips it.
    """
    pytest.importorskip("sentence_transformers")
    vector = embed(load_encoder(), [MODEL.query_prefix + REFERENCE_QUERY])[0]
    reference = FIXTURE["reference"]["embedding"]
    assert math.sumprod(vector, reference) > 0.999


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


def synthetic_result(kind: str = "cross-source") -> ExampleResult:
    return ExampleResult(
        Comparison("q", [], [], []),
        "Topic",
        kind,
        (RankRow("A", "a", 1, None, 1), RankRow("B", "b", 4, None, 6)),
    )


def test_partial_and_complete_retrieval_use_every_expected_source() -> None:
    result = synthetic_result()
    assert result.coverage("semantic", 3) == 0.5
    assert result.coverage("semantic", 5) == 1.0
    assert result.coverage("lexical", 5) == 0.0
    assert not result.all_found("semantic", 3)
    assert result.all_found("semantic", 5)
    assert not result.all_found("combined", 5)
    assert result.coverage("semantic", 0) == 0.0


def test_grouped_coverage_gives_each_query_equal_weight() -> None:
    multi = synthetic_result()
    single = ExampleResult(multi.comparison, "Other", "specific", multi.expected[:1])
    rows = summary_rows([single, multi])
    semantic = next(
        row for row in rows if row["Type"] == "All queries" and row["Mode"] == "Semantisch"
    )
    assert semantic == {
        "Type": "All queries",
        "Mode": "Semantisch",
        "Queries": 2,
        "Coverage@3": 0.75,
        "All found@3": 1,
        "Coverage@5": 1.0,
        "All found@5": 2,
    }
    assert {row["Type"] for row in rows} == {"All queries", "Specific", "Cross-source"}
    assert summary_rows([]) == []


def test_filters_combine_type_topic_and_misses_and_preserve_order() -> None:
    missed = synthetic_result()
    complete = ExampleResult(
        Comparison("complete", [], [], []),
        "Other",
        "specific",
        (RankRow("A", "a", 1, 1, 1),),
    )
    results = [missed, complete]
    assert filter_examples(results) == results
    assert filter_examples(results, misses_only=True) == [missed]
    assert filter_examples(results, kind="specific") == [complete]
    assert filter_examples(results, topic="Topic") == [missed]
    assert filter_examples(results, kind="specific", topic="Topic") == []
    assert filter_examples(results, kind="specific", topic="Other", misses_only=True) == []


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
    assert result.coverage("semantic") == 0.5
    assert not result.all_found("combined")
    row = example_rows([result])[0]
    assert row["Semantisch"] == "1, — ✗"
    assert row["Lexikalisch"] == "—, — ✗"
    assert row["Expected publications"] == "Rhein / absent"


@pytest.mark.parametrize("keys", [[], ["u", "u"]])
def test_evaluator_rejects_empty_or_duplicate_expected_sources(keys: list[str]) -> None:
    with pytest.raises(ValueError, match="nonempty and distinct"):
        evaluate_example({"expected_urls": keys}, LEXICAL)


def test_markdown_table_escapes_delimiters_and_newlines() -> None:
    assert markdown_table([{"Query": "a|b\nc"}]).splitlines()[-1] == r"| a\|b c |"
    assert markdown_table([]) == "No queries match the filters."


def test_load_comparison_matches_the_saved_examples() -> None:
    lexical, items = load_comparison()
    assert len(lexical.chunks) == len(INDEX.chunks)
    assert items == ALL_ITEMS
    assert {item["expected_url"] for item in items[: len(ITEMS)]} == {
        item["expected_url"] for item in ITEMS
    }
    assert all(item["kind"] != "reference" for item in items)
    assert {item["kind"] for item in items} == set(KIND_NAMES)


def test_python_model_reproduces_all_expanded_query_vectors() -> None:
    pytest.importorskip("sentence_transformers")
    vectors = embed(load_encoder(), [MODEL.query_prefix + case.query for case in QUERY_EXAMPLES])
    for vector, item in zip(vectors, FIXTURE["comparison_references"], strict=True):
        assert math.sumprod(vector, item["embedding"]) > 0.999, item["query"]


def test_notebook_shows_both_expected_links_for_a_cross_source_query() -> None:
    from types import SimpleNamespace

    from scripts.comparison_report import build_report

    query = build_report().queries[-1]
    outputs, defs = compare_app.run(
        defs={"filtered": [query], "page_picker": SimpleNamespace(value=0)}
    )
    assert defs["selected"] == query
    texts = [getattr(output, "text", "") for output in outputs]
    assert any("Erwartete Publikationen" in text for text in texts)
    for row in query.expected:
        assert any(row.key in text for text in texts)
    assert "encoder" not in defs["cache"]


def test_notebook_handles_filters_with_no_matches() -> None:
    from types import SimpleNamespace

    outputs, defs = compare_app.run(
        defs={
            "kind_filter": SimpleNamespace(value="synonyms"),
            "topic_filter": SimpleNamespace(value="Schweizerhalle"),
            "misses_only": SimpleNamespace(value=False),
        }
    )
    assert defs["filtered"] == []
    assert "picker" not in defs and "selected" not in defs
    assert any("Keine Fragen passen" in getattr(output, "text", "") for output in outputs)


def test_free_query_reuses_the_encoder_and_clears_expected_source_annotations() -> None:
    from types import SimpleNamespace

    class Encoder:
        def encode(
            self, texts: list[str], *, normalize_embeddings: bool, batch_size: int
        ) -> list[list[float]]:
            assert texts == [MODEL.query_prefix + "Rhein"]
            assert normalize_embeddings and batch_size == 32
            return [ITEMS[0]["embedding"]]

    cache = {"encoder": Encoder(), "lexical": LEXICAL}
    outputs, defs = compare_app.run(
        defs={
            "free": SimpleNamespace(value=" Rhein "),
            "picker": None,
            "cache": cache,
        }
    )
    assert defs["selected"].expected == []
    assert defs["selected"].query == "Rhein"
    assert defs["cache"] is cache
    assert any("keine erwarteten Quellen" in getattr(output, "text", "") for output in outputs)
