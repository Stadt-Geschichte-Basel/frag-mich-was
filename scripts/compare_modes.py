"""Compare the three search modes on one query.

The notebook ``compare.py`` shows the result. Print the reference table in a terminal::

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
from scripts.comparison_queries import KIND_NAMES, QUERY_EXAMPLES, REFERENCE_KINDS

Ranking = list[tuple[Chunk, float]]

# A reference query passes in a mode when its expected publication ranks this high.
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


def top_keys(comparison: Comparison, mode: Mode, top_k: int = TOP_K) -> list[str]:
    """Return the publication keys that a mode shows, best first.

    >>> a = Chunk(id="a", title="A", text="x", source="a.md", embedding=[1.0])
    >>> top_keys(Comparison("q", [(a, 1.0)], [], []), "semantic")
    ['a']
    """
    return [publication(chunk) for chunk, _score in comparison.ranking(mode)[:top_k]]


def overlap(comparison: Comparison, first: Mode, second: Mode, top_k: int = TOP_K) -> int:
    """Count the publications that two modes both show.

    >>> a = Chunk(id="a", title="A", text="x", source="a.md", embedding=[1.0])
    >>> b = Chunk(id="b", title="B", text="y", source="b.md", embedding=[1.0])
    >>> comparison = Comparison("q", [(a, 1.0), (b, 0.5)], [(b, 2.0)], [])
    >>> overlap(comparison, "semantic", "lexical"), overlap(comparison, "semantic", "lexical", 1)
    (1, 0)
    """
    return len(set(top_keys(comparison, first, top_k)) & set(top_keys(comparison, second, top_k)))


def lexical_excerpts(comparison: Comparison, top_k: int = TOP_K) -> int:
    """Count the combined results whose excerpt is not the best semantic passage.

    The excerpt of such a result comes from the lexical ranking.

    >>> s = Chunk(id="s", title="A", text="x", source="a.md", url="u", embedding=[1.0])
    >>> l = Chunk(id="l", title="A", text="y", source="a.md", url="u", embedding=[1.0])
    >>> lexical_excerpts(Comparison("q", [(s, 1.0)], [(l, 1.0)], [(l, 0.5)]))
    1
    >>> lexical_excerpts(Comparison("q", [(s, 1.0)], [(l, 1.0)], [(s, 0.5)]))
    0
    """
    semantic = {publication(chunk): chunk.id for chunk, _score in comparison.semantic}
    shown = comparison.combined[:top_k]
    return sum(1 for chunk, _score in shown if semantic.get(publication(chunk)) != chunk.id)


@dataclass(frozen=True)
class RankRow:
    """The rank of one publication in each mode. ``None`` means that the mode skips it.

    >>> RankRow("Titel", "u", 1, None, 2).lexical is None
    True
    """

    title: str
    key: str
    semantic: int | None
    lexical: int | None
    combined: int | None


def rank_table(comparison: Comparison, top_k: int = TOP_K) -> list[RankRow]:
    """List each publication that any mode shows, with its rank in every mode.

    The rows follow the combined rank. A publication that the combined mode does not show
    comes last.

    >>> a = Chunk(id="a", title="A", text="x", source="a.md", embedding=[1.0])
    >>> b = Chunk(id="b", title="B", text="y", source="b.md", embedding=[1.0])
    >>> comparison = Comparison("q", [(a, 1.0), (b, 0.5)], [(b, 2.0)], [(b, 0.5), (a, 0.4)])
    >>> [(row.key, row.semantic, row.lexical, row.combined) for row in rank_table(comparison, 1)]
    [('b', 2, 1, 1), ('a', 1, None, 2)]
    """
    titles: dict[str, str] = {}
    for mode in MODE_NAMES:
        for chunk, _score in comparison.ranking(mode)[:top_k]:
            titles.setdefault(publication(chunk), chunk.title)
    rows = [
        RankRow(
            title,
            key,
            position(comparison, "semantic", key),
            position(comparison, "lexical", key),
            position(comparison, "combined", key),
        )
        for key, title in titles.items()
    ]
    rows.sort(key=lambda row: (row.combined is None, row.combined or 0, row.key))
    return rows


@dataclass(frozen=True)
class ReferenceResult:
    """How the modes treat one reference query with a known publication.

    >>> ReferenceResult("q", "u", 1, None, 3, 2, 1, 0).passes("lexical")
    False
    """

    query: str
    expected_url: str
    semantic: int | None
    lexical: int | None
    combined: int | None
    combined_with_semantic: int
    combined_with_lexical: int
    lexical_excerpts: int

    def rank(self, mode: Mode) -> int | None:
        """Return the rank of the expected publication in a mode.

        >>> ReferenceResult("q", "u", 1, None, 3, 2, 1, 0).rank("combined")
        3
        """
        return {"semantic": self.semantic, "lexical": self.lexical, "combined": self.combined}[mode]

    def passes(self, mode: Mode) -> bool:
        """Say whether the expected publication ranks in the top ``EXPECTED_TOP`` of a mode.

        >>> ReferenceResult("q", "u", 1, None, 3, 2, 1, 0).passes("semantic")
        True
        """
        position = self.rank(mode)
        return position is not None and position <= EXPECTED_TOP


def evaluate(item: Mapping[str, Any], lexical: LexicalIndex) -> ReferenceResult:
    """Run one reference query from the fixture in all three modes.

    >>> a = Chunk(id="a", title="Basel", text="Der Rhein.", source="a.md", url="u", embedding=[1.0])
    >>> item = {"query": "Rhein", "expected_url": "u", "embedding": [1.0]}
    >>> evaluate(item, build_lexical_index([a])).passes("combined")
    True
    """
    comparison = compare(item["query"], item["embedding"], lexical)
    key = item["expected_url"]
    return ReferenceResult(
        query=item["query"],
        expected_url=key,
        semantic=position(comparison, "semantic", key),
        lexical=position(comparison, "lexical", key),
        combined=position(comparison, "combined", key),
        combined_with_semantic=overlap(comparison, "combined", "semantic"),
        combined_with_lexical=overlap(comparison, "combined", "lexical"),
        lexical_excerpts=lexical_excerpts(comparison),
    )


def reference_items(fixture: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Return the reference queries of the fixture: the chapter query, then the story queries.

    >>> [item["query"] for item in reference_items({"reference": {"query": "a"}, "story_references": [{"query": "b"}]})]
    ['a', 'b']
    """
    return [fixture["reference"], *fixture["story_references"]]


def pass_counts(results: Sequence[ReferenceResult]) -> dict[Mode, int]:
    """Count the reference queries that pass in each mode.

    >>> pass_counts([ReferenceResult("q", "u", 1, None, 3, 2, 1, 0)])
    {'semantic': 1, 'lexical': 0, 'combined': 1}
    """
    return {mode: sum(result.passes(mode) for result in results) for mode in MODE_NAMES}


def format_rank(value: int | None) -> str:
    """Show a rank. Show a dash when the mode skips the publication.

    >>> format_rank(3), format_rank(None)
    ('3', '—')
    """
    return "—" if value is None else str(value)


def reference_table(results: Sequence[ReferenceResult]) -> str:
    """Format the reference results as a Markdown table.

    >>> print(reference_table([ReferenceResult("Frage?", "u", 1, None, 3, 2, 1, 0)]))
    | Query | Semantisch | Lexikalisch | Kombiniert | Combined with semantic top 5 | Combined with lexical top 5 | Lexical excerpts |
    | --- | --- | --- | --- | --- | --- | --- |
    | Frage? | 1 | — | 3 | 2 | 1 | 0 |
    """
    header = (
        "| Query | "
        + " | ".join(MODE_NAMES.values())
        + " | Combined with semantic top 5 | Combined with lexical top 5 | Lexical excerpts |"
    )
    lines = [header, "| " + " | ".join(["---"] * 7) + " |"]
    for result in results:
        ranks = " | ".join(format_rank(result.rank(mode)) for mode in MODE_NAMES)
        lines.append(
            f"| {result.query} | {ranks} | {result.combined_with_semantic} "
            f"| {result.combined_with_lexical} | {result.lexical_excerpts} |"
        )
    return "\n".join(lines)


def load_reference() -> tuple[LexicalIndex, list[Mapping[str, Any]]]:
    """Load the committed index and fixture. Build the lexical index.

    >>> lexical, items = load_reference()
    >>> len(items) >= 1 and len(lexical.chunks) > 0
    True
    """
    index = load_index(INDEX_FILE.read_text(encoding="utf-8"))
    fixture = json.loads(FIXTURE_FILE.read_text(encoding="utf-8"))
    return build_lexical_index(index.chunks), reference_items(fixture)


@dataclass(frozen=True)
class ExampleResult:
    """Rank every expected source of one example.

    >>> ExampleResult(Comparison("q", [], [], []), "Topic", "specific", ()).query
    'q'
    """

    comparison: Comparison
    topic: str
    kind: str
    expected: tuple[RankRow, ...]

    @property
    def query(self) -> str:
        """Return the query text.

        >>> ExampleResult(Comparison("q", [], [], []), "T", "specific", ()).query
        'q'
        """
        return self.comparison.query

    def coverage(self, mode: Mode, top_k: int = EXPECTED_TOP) -> float:
        """Return the fraction of expected sources in the top results.

        >>> row = RankRow("A", "u", 1, None, 4)
        >>> result = ExampleResult(Comparison("q", [], [], []), "T", "specific", (row,))
        >>> result.coverage("semantic"), result.coverage("lexical")
        (1.0, 0.0)
        """
        return sum(
            (place := getattr(row, mode)) is not None and place <= top_k for row in self.expected
        ) / len(self.expected)

    def all_found(self, mode: Mode, top_k: int = EXPECTED_TOP) -> bool:
        """Say whether all expected sources appear in the top results.

        >>> row = RankRow("A", "u", 1, None, 4)
        >>> ExampleResult(Comparison("q", [], [], []), "T", "specific", (row,)).all_found("combined")
        False
        """
        return self.coverage(mode, top_k) == 1.0


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
        for item in reference_items(fixture)
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


def filter_examples(
    results: Sequence[ExampleResult],
    kind: str = "All",
    topic: str = "All",
    misses_only: bool = False,
) -> list[ExampleResult]:
    """Select examples by type, topic, and a miss in any mode's top three.

    >>> filter_examples([], misses_only=True)
    []
    """
    return [
        result
        for result in results
        if (kind == "All" or result.kind == kind)
        and (topic == "All" or result.topic == topic)
        and (not misses_only or any(not result.all_found(mode) for mode in MODE_NAMES))
    ]


def summary_rows(results: Sequence[ExampleResult]) -> list[dict[str, str | int | float]]:
    """Report macro coverage and complete retrieval, overall and by query type.

    >>> summary_rows([])
    []
    """
    rows: list[dict[str, str | int | float]] = []
    for kind, label in {"All": "All queries", **KIND_NAMES}.items():
        selected = filter_examples(results, kind=kind)
        if not selected:
            continue
        for mode, name in MODE_NAMES.items():
            row: dict[str, str | int | float] = {
                "Type": label,
                "Mode": name,
                "Queries": len(selected),
            }
            for limit in (EXPECTED_TOP, TOP_K):
                row[f"Coverage@{limit}"] = sum(
                    result.coverage(mode, limit) for result in selected
                ) / len(selected)
                row[f"All found@{limit}"] = sum(
                    result.all_found(mode, limit) for result in selected
                )
            rows.append(row)
    return rows


def example_rows(results: Sequence[ExampleResult]) -> list[dict[str, str]]:
    """Show each query with its expected-source ranks in a stable order.

    >>> example_rows([])
    []
    """
    return [
        {
            "Query": result.query,
            "Type": KIND_NAMES[result.kind],
            "Topic": result.topic,
            "Expected publications": " / ".join(row.title for row in result.expected),
            **{
                name: ", ".join(format_rank(getattr(row, mode)) for row in result.expected)
                + (" ✓" if result.all_found(mode) else " ✗")
                for mode, name in MODE_NAMES.items()
            },
        }
        for result in results
    ]


def markdown_table(rows: Sequence[Mapping[str, Any]]) -> str:
    """Format report rows and escape Markdown table delimiters.

    >>> print(markdown_table([{"Query": "a|b\\nc"}]))
    | Query |
    | --- |
    | a\\|b c |
    >>> markdown_table([])
    'No queries match the filters.'
    """
    if not rows:
        return "No queries match the filters."
    headers = list(rows[0])
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        values = [str(row[key]).replace("|", "\\|").replace("\n", " ") for key in headers]
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


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
    """Print per-source ranks and grouped retrieval measurements.

    >>> main()  # doctest: +ELLIPSIS
    | Query | ...
    ...
    """
    lexical, items = load_comparison()
    results = [evaluate_example(item, lexical) for item in items]
    print(markdown_table(example_rows(results)))
    print(
        "\nRanks follow the expected-publication order. A tick requires every source in the top 3."
    )
    rows = summary_rows(results)
    display = [
        {key: f"{value:.1%}" if key.startswith("Coverage") else value for key, value in row.items()}
        for row in rows
    ]
    print("\n" + markdown_table(display))
    print(
        "\nCoverage is the mean fraction of expected sources found per query. All found counts complete queries."
    )
    print("The expected sources are supported examples, not exhaustive relevance judgements.")


if __name__ == "__main__":
    main()
