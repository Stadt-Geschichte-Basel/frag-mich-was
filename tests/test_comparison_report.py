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
    insights_html,
    native_free_query,
    ranks_html,
    results_html,
    safe_source_url,
    summary_html,
    table_html,
)
from scripts import comparison_report
from scripts.build_index import MODEL
from scripts.compare_modes import MODE_NAMES, evaluate_example, load_comparison, rank_table

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
        assert [row.model_dump() for row in query.ranks] == [
            asdict(row) for row in rank_table(result.comparison)
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
    assert REPORT.summary[0].coverage3 == pytest.approx(0.8977272727)
    assert REPORT.summary[2].complete5 == 41


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


def test_report_filters_combine_topics_types_and_misses() -> None:
    queries = REPORT.queries
    assert filter_queries(queries) == queries
    assert len(filter_queries(queries, kind="cross-source")) == 4
    assert len(filter_queries(queries, topic="Schweizerhalle")) == 2
    assert filter_queries(queries, kind="synonyms", topic="Schweizerhalle") == []
    missed = filter_queries(queries, misses_only=True)
    assert missed and len(missed) < len(queries)
    assert all(any(not all_found(query, mode) for mode in MODE_NAMES) for query in missed)
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
    assert "<img>" not in ranks_html([row], "Ränge")
    assert "89,8%" in summary_html(REPORT.summary)
    assert "Alle Fragen" in summary_html(REPORT.summary)
    assert "Mehrere Quellen" in summary_html(REPORT.summary)


def test_local_free_queries_load_and_reuse_optional_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class Encoder:
        def encode(
            self, texts: list[str], *, normalize_embeddings: bool, batch_size: int
        ) -> list[list[float]]:
            assert texts == [MODEL.query_prefix + "Rhein"]
            assert normalize_embeddings and batch_size == 32
            return [ITEMS[0]["embedding"]]

    def load() -> Encoder:
        calls.append("model")
        return Encoder()

    def lexical() -> tuple[Any, list[Any]]:
        calls.append("index")
        return LEXICAL, []

    monkeypatch.setattr(comparison_report, "load_encoder", load)
    monkeypatch.setattr(comparison_report, "load_comparison", lexical)
    cache: dict[str, Any] = {}
    first = native_free_query("Rhein", cache)
    second = native_free_query("Rhein", cache)
    assert first == second
    assert first.kind == "free" and first.expected == []
    assert calls == ["index", "model"]
    assert not all_found(first, "semantic")
    assert "keine erwarteten Quellen" in expected_html(first)


def test_insights_use_report_counts_and_a_measured_ranking_loss() -> None:
    output = insights_html(REPORT)
    assert "Was der Vergleich zeigt" in output
    assert "18 von 18" in output
    assert "8 von 9" in output and "4 von 9" in output
    assert "Schweizerhalle" in output and "Rang 2" in output and "Rang 8" in output
    assert "bei 3 von 4" in output
    assert "44 ausgewählten Beispiele" in output
    assert insights_html(REPORT.model_copy(update={"summary": [], "queries": []})) == ""
    changed = REPORT.model_copy(
        update={
            "summary": [
                row.model_copy(update={"complete3": 0, "complete5": 0}) for row in REPORT.summary
            ],
            "queries": [
                REPORT.queries[0].model_copy(
                    update={
                        "topic": "<img>",
                        "expected": [
                            REPORT.queries[0]
                            .expected[0]
                            .model_copy(update={"semantic": 2, "combined": 8})
                        ],
                    }
                )
            ],
        }
    )
    altered = insights_html(changed)
    assert "18 von 18" not in altered and "0 von 9" in altered
    assert "<img>" not in altered and "&lt;img&gt;" in altered
    assert "1 ausgewählten Beispiele" in altered


def test_public_categories_describe_intent_without_regression_cohorts() -> None:
    import json
    from collections import Counter

    from scripts.build_index import FIXTURE_FILE
    from scripts.compare_modes import reference_items
    from scripts.comparison_queries import REFERENCE_KINDS

    assert Counter(query.kind for query in REPORT.queries) == {
        "specific": 18,
        "synonyms": 9,
        "complex": 13,
        "cross-source": 4,
    }
    fixture = json.loads(FIXTURE_FILE.read_text())
    assert set(REFERENCE_KINDS) == {item["expected_url"] for item in reference_items(fixture)}
    assert {row.kind for row in REPORT.summary} == {
        "all",
        "specific",
        "synonyms",
        "complex",
        "cross-source",
    }
    assert [query.topic.casefold() for query in REPORT.queries] == sorted(
        query.topic.casefold() for query in REPORT.queries
    )
    assert "Referenzfragen" not in summary_html(REPORT.summary)
