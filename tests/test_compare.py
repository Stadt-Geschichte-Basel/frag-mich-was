"""Tests for the mode comparison, the reference table, and the comparison notebook."""

import json
import math
import subprocess
import sys
from pathlib import Path

import pytest

from app import (
    TOP_K,
    Chunk,
    build_lexical_index,
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
    RankRow,
    ReferenceResult,
    compare,
    evaluate,
    format_rank,
    lexical_excerpts,
    load_reference,
    main,
    overlap,
    pass_counts,
    position,
    publication,
    rank_table,
    reference_items,
    reference_table,
    top_keys,
)

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


def test_reference_items_cover_the_chapter_and_the_story_queries() -> None:
    assert [item["query"] for item in ITEMS][0] == REFERENCE_QUERY
    assert len(ITEMS) == 1 + len(FIXTURE["story_references"])


@pytest.mark.parametrize("item", ITEMS, ids=lambda item: item["query"][:30])
def test_comparison_agrees_with_the_search_modes(item: dict) -> None:
    """The comparison and the page rank alike, so that the notebook shows what users get."""
    comparison = compare(item["query"], item["embedding"], LEXICAL)
    for mode in MODE_NAMES:
        vector = None if mode == "lexical" else item["embedding"]
        shown = ids(search(mode, item["query"], vector, LEXICAL))
        assert ids(comparison.ranking(mode)[:TOP_K]) == shown, mode


@pytest.mark.parametrize("item", ITEMS, ids=lambda item: item["query"][:30])
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


@pytest.mark.parametrize("item", ITEMS, ids=lambda item: item["query"][:30])
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
    assert output.count("\n| ") == len(ITEMS) + 1
    assert f"top {EXPECTED_TOP}" in output


def test_load_reference_matches_the_committed_files() -> None:
    lexical, items = load_reference()
    assert len(lexical.chunks) == len(INDEX.chunks)
    assert items == ITEMS


# The notebook.


def test_notebook_runs_and_shows_the_reference_results() -> None:
    _outputs, defs = compare_app.run()
    assert [result.query for result in defs["results"]] == [item["query"] for item in ITEMS]
    assert defs["results"] == [evaluate(item, LEXICAL) for item in ITEMS]
    # The first reference query is the default of the picker. No model loads for it.
    assert defs["comparison"].query == ITEMS[0]["query"]
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
