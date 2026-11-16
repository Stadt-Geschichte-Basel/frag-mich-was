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


def main() -> None:
    """Print the reference table and the pass counts.

    >>> main()  # doctest: +ELLIPSIS
    | Query | ...
    ...
    """
    lexical, items = load_reference()
    results = [evaluate(item, lexical) for item in items]
    print(reference_table(results))
    counts = pass_counts(results)
    summary = ", ".join(f"{MODE_NAMES[mode]} {count}" for mode, count in counts.items())
    print(
        f"\nThe expected publication ranks in the top {EXPECTED_TOP} for {summary} of {len(results)}."
    )


if __name__ == "__main__":
    main()
