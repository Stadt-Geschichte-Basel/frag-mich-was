"""Build compact comparison data with the same ranking functions as the search.

>>> callable(build_report)
True
"""

from collections.abc import Sequence
from dataclasses import asdict
from typing import Any

from compare import ComparisonReport, DisplayPassage, PublicationRanks, QueryReport, SummaryRow
from scripts.build_index import MODEL, embed, load_encoder
from scripts.compare_modes import (
    KIND_NAMES,
    MODE_NAMES,
    Comparison,
    ExampleResult,
    compare,
    evaluate_example,
    lexical_excerpts,
    load_comparison,
    overlap,
    rank_table,
    summary_rows,
)


def query_report(
    comparison: Comparison,
    topic: str,
    kind: str,
    expected: Sequence[PublicationRanks],
) -> QueryReport:
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
            for chunk, _ in comparison.ranking(mode)[:5]
        ]
        for mode in MODE_NAMES
    }
    return QueryReport.model_validate(
        {
            "query": comparison.query,
            "topic": topic,
            "kind": kind,
            "expected": list(expected),
            "ranks": [PublicationRanks(**asdict(row)) for row in rank_table(comparison)],
            **rankings,
            "publications": len(comparison.semantic),
            "lexical_matches": len(comparison.lexical),
            "semantic_overlap": overlap(comparison, "combined", "semantic"),
            "lexical_overlap": overlap(comparison, "combined", "lexical"),
            "lexical_excerpts": lexical_excerpts(comparison),
        }
    )


def build_report(results: Sequence[ExampleResult] | None = None) -> ComparisonReport:
    """Build a validated report from saved query vectors. No model is required.

    >>> callable(build_report)
    True
    """
    if results is None:
        lexical, items = load_comparison()
        results = [evaluate_example(item, lexical) for item in items]
    kinds = {label: kind for kind, label in KIND_NAMES.items()} | {"All queries": "all"}
    modes = {label: mode for mode, label in MODE_NAMES.items()}
    intent_order = {kind: number for number, kind in enumerate(KIND_NAMES)}
    return ComparisonReport(
        queries=sorted(
            [
                query_report(
                    result.comparison,
                    result.topic,
                    result.kind,
                    [PublicationRanks(**asdict(row)) for row in result.expected],
                )
                for result in results
            ],
            key=lambda query: (
                query.topic.casefold(),
                intent_order[query.kind],
                query.query.casefold(),
            ),
        ),
        summary=[
            SummaryRow.model_validate(
                {
                    "kind": kinds[str(row["Type"])],
                    "mode": modes[str(row["Mode"])],
                    "queries": row["Queries"],
                    "coverage3": row["Coverage@3"],
                    "complete3": row["All found@3"],
                    "coverage5": row["Coverage@5"],
                    "complete5": row["All found@5"],
                }
            )
            for row in summary_rows(results)
        ],
    )


def free_query_report(query: str, cache: dict[str, Any]) -> QueryReport:
    """Load the encoder only for a local free query and reuse it afterwards.

    >>> callable(free_query_report)
    True
    """
    if "lexical" not in cache:
        cache["lexical"] = load_comparison()[0]
    if "encoder" not in cache:
        cache["encoder"] = load_encoder()
    vector = embed(cache["encoder"], [MODEL.query_prefix + query])[0]
    return query_report(compare(query, vector, cache["lexical"]), "Freie Eingabe", "free", [])
