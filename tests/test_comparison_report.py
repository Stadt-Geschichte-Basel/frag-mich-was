"""Check the public report, its validation boundary, and escaped German rendering."""

from dataclasses import asdict
from typing import Any

import pytest
from pydantic import ValidationError

from compare import (
    ComparisonReport,
    DisplayPassage,
    PublicationRanks,
    QueryReport,
    all_found,
    catalogue_html,
    expected_html,
    filter_queries,
    format_rank,
    results_html,
    safe_source_url,
    summary_html,
    table_html,
)
from scripts import comparison_report
from scripts.compare_modes import MODE_NAMES, evaluate_example, load_comparison
from scripts.comparison_queries import KINDS

LEXICAL, ITEMS = load_comparison()
RESULTS = [evaluate_example(item, LEXICAL) for item in ITEMS]
REPORT = comparison_report.build_report(RESULTS)


def test_report_matches_every_saved_ranking_and_omits_embeddings() -> None:
    assert len(REPORT.queries) == 44
    results_by_query = {result.query: result for result in RESULTS}
    for query in REPORT.queries:
        result = results_by_query[query.query]
        assert query.query == result.query
        assert [row.model_dump() for row in query.expected] == [
            asdict(row) for row in result.expected
        ]
        for mode in MODE_NAMES:
            assert [row.text for row in getattr(query, mode)] == [
                chunk.text for chunk, _ in result.comparison.ranking(mode)[:5]
            ]
            for limit in (3, 5):
                assert all_found(query, mode, limit) == result.all_found(mode, limit)
    encoded = REPORT.model_dump_json()
    assert '"embedding"' not in encoded and '"source"' not in encoded
    assert len(encoded.encode()) < 1_000_000
    assert ComparisonReport.model_validate_json(encoded) == REPORT
    assert comparison_report.build_report(RESULTS) == REPORT
    assert (REPORT.summary[0].complete3, REPORT.summary[2].complete5) == (38, 41)


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "https://example.org/a",
        "https://me@doi.org/a",
        "https://doi.org/a\n",
        " https://doi.org/a",
        "https://doi.org/a\x00b",
        "https://[bad",
    ],
)
def test_publication_urls_reject_unsafe_values(url: str) -> None:
    with pytest.raises(ValueError):
        safe_source_url(url)
    with pytest.raises(ValidationError):
        PublicationRanks(title="A", key=url)


@pytest.mark.parametrize(
    "change",
    [
        {"schema_version": 99},
        {"queries": []},
        {"summary": []},
        {"unexpected": True},
    ],
)
def test_report_rejects_invalid_payloads(change: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        ComparisonReport.model_validate(REPORT.model_dump() | change)


def test_saved_queries_need_distinct_expected_sources_and_positive_ranks() -> None:
    data = REPORT.queries[0].model_dump()
    with pytest.raises(ValidationError, match="nonempty and distinct"):
        QueryReport.model_validate(data | {"expected": []})
    with pytest.raises(ValidationError, match="nonempty and distinct"):
        QueryReport.model_validate(data | {"expected": [data["expected"][0]] * 2})
    with pytest.raises(ValidationError):
        PublicationRanks(title="A", key="https://doi.org/10.1/a", semantic=0)
    with pytest.raises(ValidationError):
        QueryReport.model_validate(data | {"combined": data["combined"] * 2})


def test_report_filter_selects_one_type_and_keeps_the_order() -> None:
    queries = REPORT.queries
    assert filter_queries(queries) == queries
    cross = filter_queries(queries, kind="cross-source")
    assert len(cross) == 4 and all(query.kind == "cross-source" for query in cross)
    assert filter_queries(queries, kind="synonyms") == [
        query for query in queries if query.kind == "synonyms"
    ]
    absent = REPORT.queries[0].expected[0].model_copy(update={"lexical": None})
    query = REPORT.queries[0].model_copy(update={"expected": [absent]})
    assert not all_found(query, "lexical")
    assert format_rank(absent.lexical) == "—"
    assert "— ✗" in catalogue_html([query])


def test_html_renderers_escape_sources_questions_and_attributes() -> None:
    passage = DisplayPassage(
        title='<script>"A"</script>',
        text="<img onerror=x> & text",
        url='https://doi.org/10.1/a?x="&y=2',
        content_type="data_story",
        coverage="summary",
    )
    output = results_html([passage])
    assert "<script>" not in output and "<img" not in output
    assert "&lt;script&gt;" in output and "&lt;img" in output
    assert "&quot;&amp;y=2" in output
    assert "Originalstory öffnen" in output and "Nur Zusammenfassung" in output
    assert "Originalkapitel öffnen" in results_html(
        [passage.model_copy(update={"content_type": "chapter", "coverage": "full_text"})]
    )
    assert "Keine Textstelle gefunden" in results_html([])
    table = table_html(["<header>"], [["<script>"]], '"<caption>')
    assert "<header>" not in table and "<script>" not in table
    assert 'aria-label="&quot;&lt;caption&gt;"' in table
    query = REPORT.queries[0].model_copy(update={"query": "<script>"})
    assert "<script>" not in catalogue_html([query])
    row = PublicationRanks(title="<img>", key='https://doi.org/10.1/a?x="&y=2')
    query = query.model_copy(update={"expected": [row]})
    assert "<img>" not in expected_html(query)
    assert "&quot;&amp;y=2" in expected_html(query)
    assert 'target="_blank" rel="noopener noreferrer"' in expected_html(query)
    assert "Alle Fragen" in summary_html(REPORT.summary)
    assert "38 von 44" in summary_html(REPORT.summary)
    assert "Mehrere Quellen" in summary_html(REPORT.summary)


def test_the_static_insights_of_the_page_match_the_report() -> None:
    """The page states these findings in prose. The report must still support them."""
    by_kind = {(row.kind, row.mode): row for row in REPORT.summary}
    specific = [by_kind["specific", mode] for mode in MODE_NAMES]
    assert all(row.complete3 == row.queries for row in specific)
    synonyms = {mode: by_kind["synonyms", mode].complete3 for mode in MODE_NAMES}
    assert synonyms["lexical"] < synonyms["semantic"] and synonyms["lexical"] < synonyms["combined"]
    schweizerhalle = next(
        source
        for query in REPORT.queries
        if query.topic == "Schweizerhalle" and query.kind == "complex"
        for source in query.expected
    )
    assert (schweizerhalle.semantic, schweizerhalle.combined) == (2, 8)
    cross = {mode: by_kind["cross-source", mode].complete5 for mode in MODE_NAMES}
    assert cross["combined"] > cross["semantic"] and cross["combined"] > cross["lexical"]


def test_public_categories_describe_intent_without_regression_cohorts() -> None:
    import json
    from collections import Counter

    from scripts.build_index import FIXTURE_FILE
    from scripts.comparison_queries import REFERENCE_KINDS

    assert Counter(query.kind for query in REPORT.queries) == {
        "specific": 18,
        "synonyms": 9,
        "complex": 13,
        "cross-source": 4,
    }
    fixture = json.loads(FIXTURE_FILE.read_text())
    originals = [fixture["reference"], *fixture["story_references"]]
    assert set(REFERENCE_KINDS) == {item["expected_url"] for item in originals}
    assert {row.kind for row in REPORT.summary} == {"all", *KINDS}
    assert [query.topic.casefold() for query in REPORT.queries] == sorted(
        query.topic.casefold() for query in REPORT.queries
    )
    assert "Referenzfragen" not in summary_html(REPORT.summary)
