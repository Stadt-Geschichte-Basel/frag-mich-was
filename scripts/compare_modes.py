"""Compare the three search modes on the saved example queries.

The notebook ``compare.py`` shows the result. Print the summary in a terminal::

    uv run python -m scripts.compare_modes
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app import (
    TOP_K,
    Chunk,
    LexicalIndex,
    Mode,
    build_lexical_index,
    fuse,
    lexical_rank,
    load_index,
    rank,
)
from scripts.build_index import FIXTURE_FILE, INDEX_FILE
from scripts.comparison_queries import KINDS, QUERY_EXAMPLES, REFERENCE_KINDS, QueryKind

Ranking = list[tuple[Chunk, float]]

# A query is complete in the top N when every expected publication ranks N or better.
EXPECTED_TOP = 3
MODE_NAMES: dict[Mode, str] = {
    "semantic": "Semantisch",
    "lexical": "Lexikalisch",
    "combined": "Kombiniert",
}


def publication(chunk: Chunk) -> str:
    """Return the key of the publication that holds the passage.

    >>> publication(Chunk(id="a", title="A", text="x", source="a.md", embedding=[1.0]))
    'a'
    >>> publication(Chunk(id="a", title="A", text="x", source="a.md", url="u", embedding=[1.0]))
    'u'
    """
    return chunk.url or chunk.id


@dataclass(frozen=True)
class Comparison:
    """The complete publication rankings of the three modes for one query.

    >>> Comparison("q", [], [], []).query
    'q'
    """

    query: str
    semantic: Ranking
    lexical: Ranking
    combined: Ranking

    def ranking(self, mode: Mode) -> Ranking:
        """Return the complete ranking of one mode.

        >>> Comparison("q", [], [], []).ranking("lexical")
        []
        """
        return {"semantic": self.semantic, "lexical": self.lexical, "combined": self.combined}[mode]


def compare(query: str, vector: Sequence[float], lexical: LexicalIndex) -> Comparison:
    """Rank the passages of the index in all three modes. Each ranking is complete.

    >>> a = Chunk(id="a", title="Basel", text="Der Rhein.", source="a.md", embedding=[1.0])
    >>> comparison = compare("Rhein", [1.0], build_lexical_index([a]))
    >>> [len(comparison.ranking(mode)) for mode in MODE_NAMES]
    [1, 1, 1]
    """
    semantic = rank(vector, lexical.chunks, None)
    lexical_ranking = lexical_rank(lexical, query, None)
    return Comparison(query, semantic, lexical_ranking, fuse(semantic, lexical_ranking, None))


def position(comparison: Comparison, mode: Mode, key: str) -> int | None:
    """Return the one-based rank of a publication in a mode, or ``None`` if the mode skips it.

    The lexical mode skips a publication with no matching word.

    >>> a = Chunk(id="a", title="A", text="x", source="a.md", embedding=[1.0])
    >>> comparison = Comparison("q", [(a, 1.0)], [], [(a, 0.5)])
    >>> position(comparison, "semantic", "a"), position(comparison, "lexical", "a")
    (1, None)
    """
    for number, (chunk, _score) in enumerate(comparison.ranking(mode), start=1):
        if publication(chunk) == key:
            return number
    return None


@dataclass(frozen=True)
class RankRow:
    """The rank of one expected publication in each mode. ``None`` means that the mode skips it.

    >>> RankRow("Titel", "u", 1, None, 2).lexical is None
    True
    """

    title: str
    key: str
    semantic: int | None
    lexical: int | None
    combined: int | None


@dataclass(frozen=True)
class ExampleResult:
    """Rank every expected source of one example.

    >>> ExampleResult(Comparison("q", [], [], []), "Topic", "specific", ()).query
    'q'
    """

    comparison: Comparison
    topic: str
    kind: QueryKind
    expected: tuple[RankRow, ...]

    @property
    def query(self) -> str:
        """Return the query text.

        >>> ExampleResult(Comparison("q", [], [], []), "T", "specific", ()).query
        'q'
        """
        return self.comparison.query

    def all_found(self, mode: Mode, top_k: int = EXPECTED_TOP) -> bool:
        """Say whether all expected sources appear in the top results.

        >>> row = RankRow("A", "u", 1, None, 4)
        >>> ExampleResult(Comparison("q", [], [], []), "T", "specific", (row,)).all_found("combined")
        False
        """
        return all(
            (place := getattr(row, mode)) is not None and place <= top_k for row in self.expected
        )


def comparison_items(fixture: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Include the original references and the expanded examples.

    >>> fixture = {"reference": {"expected_url": "u"}, "story_references": [], "comparison_references": []}
    >>> comparison_items(fixture)[0]["expected_urls"]
    ['u']
    """
    topics = {
        case.expected_urls[0]: case.topic for case in QUERY_EXAMPLES if len(case.expected_urls) == 1
    }
    originals = [
        dict(
            item,
            kind=REFERENCE_KINDS.get(item["expected_url"], "specific"),
            topic=topics.get(item["expected_url"], "Original references"),
            expected_urls=[item["expected_url"]],
        )
        for item in [fixture["reference"], *fixture["story_references"]]
    ]
    return [*originals, *fixture["comparison_references"]]


def evaluate_example(item: Mapping[str, Any], lexical: LexicalIndex) -> ExampleResult:
    """Evaluate all expected sources without requiring successful retrieval.

    >>> a = Chunk(id="a", title="Basel", text="Rhein", source="a.md", url="u", embedding=[1.0])
    >>> item = {"query": "Rhein", "expected_urls": ["u"], "topic": "Fluss", "kind": "specific", "embedding": [1.0]}
    >>> evaluate_example(item, build_lexical_index([a])).all_found("semantic")
    True
    """
    keys = item["expected_urls"]
    if not keys or len(set(keys)) != len(keys):
        raise ValueError("Expected sources must be nonempty and distinct.")
    comparison = compare(item["query"], item["embedding"], lexical)
    titles = {publication(chunk): chunk.title for chunk in lexical.chunks}
    expected = tuple(
        RankRow(
            titles.get(key, key),
            key,
            position(comparison, "semantic", key),
            position(comparison, "lexical", key),
            position(comparison, "combined", key),
        )
        for key in keys
    )
    return ExampleResult(comparison, item["topic"], item["kind"], expected)


def summary_rows(results: Sequence[ExampleResult]) -> list[dict[str, str | int]]:
    """Count the complete queries in the top three and the top five, overall and by query type.

    A row skips a query type that has no query.

    >>> summary_rows([])
    []
    >>> row = RankRow("A", "u", 1, None, 4)
    >>> result = ExampleResult(Comparison("q", [], [], []), "T", "specific", (row,))
    >>> summary_rows([result])[0]
    {'kind': 'all', 'mode': 'semantic', 'queries': 1, 'complete3': 1, 'complete5': 1}
    """
    rows: list[dict[str, str | int]] = []
    for kind in ("all", *KINDS):
        selected = [result for result in results if kind in ("all", result.kind)]
        if selected:
            for mode in MODE_NAMES:
                rows.append(
                    {
                        "kind": kind,
                        "mode": mode,
                        "queries": len(selected),
                        "complete3": sum(
                            result.all_found(mode, EXPECTED_TOP) for result in selected
                        ),
                        "complete5": sum(result.all_found(mode, TOP_K) for result in selected),
                    }
                )
    return rows


def load_comparison() -> tuple[LexicalIndex, list[Mapping[str, Any]]]:
    """Load all examples with their saved vectors. No model is required.

    >>> lexical, items = load_comparison()
    >>> len(items) == 44 and len(lexical.chunks) > 0
    True
    """
    index = load_index(INDEX_FILE.read_text(encoding="utf-8"))
    fixture = json.loads(FIXTURE_FILE.read_text(encoding="utf-8"))
    return build_lexical_index(index.chunks), comparison_items(fixture)


def main() -> None:
    """Print the number of complete queries for each query type and mode.

    >>> main()  # doctest: +ELLIPSIS
    | Type | Mode | Queries | All found@3 | All found@5 |
    ...
    """
    lexical, items = load_comparison()
    rows = summary_rows([evaluate_example(item, lexical) for item in items])
    print("| Type | Mode | Queries | All found@3 | All found@5 |")
    print("| --- | --- | --- | --- | --- |")
    for row in rows:
        print(
            f"| {row['kind']} | {row['mode']} | {row['queries']} "
            f"| {row['complete3']} | {row['complete5']} |"
        )
    print(
        f"\nAll found@N: every expected source ranks in the top N. N is {EXPECTED_TOP} or {TOP_K}."
    )
    print("The expected sources are supported examples, not exhaustive relevance judgements.")


if __name__ == "__main__":
    main()
