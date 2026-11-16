"""Build compact comparison data with the same ranking functions as the search.

>>> callable(build_report)
True
"""

from collections.abc import Sequence
from dataclasses import asdict

from app import TOP_K
from compare import ComparisonReport, DisplayPassage, PublicationRanks, QueryReport, SummaryRow
from scripts.compare_modes import (
    MODE_NAMES,
    ExampleResult,
    evaluate_example,
    load_comparison,
    summary_rows,
)
from scripts.comparison_queries import KINDS


def query_report(result: ExampleResult) -> QueryReport:
    """Keep display fields and omit embeddings and complete rankings.

    >>> callable(query_report)
    True
    """
    rankings = {
        mode: [
            DisplayPassage(
                title=chunk.title,
                text=chunk.text,
                url=chunk.url or "",
                content_type=chunk.content_type,
                coverage=chunk.coverage,
            )
            for chunk, _score in result.comparison.ranking(mode)[:TOP_K]
        ]
        for mode in MODE_NAMES
    }
    return QueryReport(
        query=result.query,
        topic=result.topic,
        kind=result.kind,
        expected=[PublicationRanks(**asdict(row)) for row in result.expected],
        **rankings,
    )


def build_report(results: Sequence[ExampleResult] | None = None) -> ComparisonReport:
    """Build a validated report from saved query vectors. No model is required.

    >>> callable(build_report)
    True
    """
    if results is None:
        lexical, items = load_comparison()
        results = [evaluate_example(item, lexical) for item in items]
    queries = sorted(
        (query_report(result) for result in results),
        key=lambda query: (query.topic.casefold(), KINDS.index(query.kind), query.query.casefold()),
    )
    return ComparisonReport(
        queries=queries,
        summary=[SummaryRow.model_validate(row) for row in summary_rows(results)],
    )
