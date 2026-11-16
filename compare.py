import marimo

__generated_with = "0.25.2"
app = marimo.App(width="full", app_title="Compare the search modes")

with app.setup:
    import importlib.util

    import marimo as mo

    from app import TOP_K, render_results
    from scripts.build_index import MODEL, embed, load_encoder
    from scripts.compare_modes import (
        EXPECTED_TOP,
        MODE_NAMES,
        compare,
        evaluate,
        format_rank,
        lexical_excerpts,
        load_reference,
        overlap,
        pass_counts,
        rank_table,
    )

    # A free query needs the model. The `index` dependency group holds it.
    MODEL_AVAILABLE = importlib.util.find_spec("sentence_transformers") is not None


@app.cell
def _():
    mo.md("""
    # Compare the search modes

    This notebook runs on your machine. It is not part of the published site.
    It ranks the same passages in all three modes of the search:
    **Semantisch**, **Lexikalisch**, and **Kombiniert**.
    The logic lives in `scripts/compare_modes.py`. A test checks it.

    Run it with:

    - `uv run marimo edit compare.py` for the reference queries.
    - `uv run --group index marimo edit compare.py` to add free queries.
    """)
    return


@app.cell
def _():
    lexical, items = load_reference()
    results = [evaluate(item, lexical) for item in items]
    return items, lexical, results


@app.cell
def _(results):
    # A rank with a tick passes: the expected publication ranks in the top EXPECTED_TOP.
    def _cell(result, mode):
        return f"{format_rank(result.rank(mode))} {'✓' if result.passes(mode) else '✗'}"

    _counts = pass_counts(results)
    mo.vstack(
        [
            mo.md(f"""
            ## Reference queries

            Each query has one expected publication. The table shows its rank in each mode.
            A tick means that it ranks in the top {EXPECTED_TOP}. A dash means that the mode skips it.
            The expected publication ranks in the top {EXPECTED_TOP} for
            {", ".join(f"**{MODE_NAMES[mode]}** {count}" for mode, count in _counts.items())}
            of {len(results)} queries.
            """),
            mo.ui.table(
                [
                    {
                        "Query": result.query,
                        **{MODE_NAMES[mode]: _cell(result, mode) for mode in MODE_NAMES},
                        "Combined shares with semantic top 5": result.combined_with_semantic,
                        "Combined shares with lexical top 5": result.combined_with_lexical,
                        "Lexical excerpts in combined top 5": result.lexical_excerpts,
                    }
                    for result in results
                ],
                selection=None,
                pagination=False,
            ),
        ]
    )
    return


@app.cell
def _(items):
    picker = mo.ui.dropdown(
        options={item["query"]: number for number, item in enumerate(items)},
        value=items[0]["query"],
        label="Reference query",
        full_width=True,
    )
    free = mo.ui.text(
        label="Free query (press Enter)",
        placeholder="Needs the index dependency group"
        if not MODEL_AVAILABLE
        else "Rhein und Handel in Basel",
        disabled=not MODEL_AVAILABLE,
        full_width=True,
    )
    mo.vstack([mo.md("## One query in all three modes"), picker, free])
    return free, picker


@app.cell
def _():
    # Holds the Python model. The first free query loads it.
    cache: dict = {}
    return (cache,)


@app.cell
def _(cache, free, items, lexical, picker):
    _text = free.value.strip()
    if _text:
        # The Python model embeds the query. The browser model gives nearly the same vector.
        if "encoder" not in cache:
            with mo.status.spinner(title="Loading the model"):
                cache["encoder"] = load_encoder()
        _query, _vector = _text, embed(cache["encoder"], [MODEL.query_prefix + _text])[0]
    else:
        _item = items[picker.value]
        _query, _vector = _item["query"], _item["embedding"]
    comparison = compare(_query, _vector, lexical)
    return (comparison,)


@app.cell
def _(comparison):
    _skipped = len(comparison.semantic) - len(comparison.lexical)
    _summary = mo.md(f"""
    **Query:** {comparison.query}

    - The lexical mode matches {len(comparison.lexical)} of {len(comparison.semantic)} publications
      and skips {_skipped}.
    - The combined top {TOP_K} shares {overlap(comparison, "combined", "semantic")} publications with the
      semantic top {TOP_K} and {overlap(comparison, "combined", "lexical")} with the lexical top {TOP_K}.
    - {lexical_excerpts(comparison)} of the combined excerpts come from a passage that only the lexical
      ranking chose.
    """)
    _rows = mo.ui.table(
        [
            {
                "Publication": row.title,
                **{MODE_NAMES[mode]: format_rank(getattr(row, mode)) for mode in MODE_NAMES},
            }
            for row in rank_table(comparison)
        ],
        selection=None,
        pagination=False,
    )
    _columns = mo.hstack(
        [
            mo.vstack(
                [
                    mo.md(f"### {name}"),
                    mo.Html(render_results(comparison.ranking(mode)[:TOP_K])),
                ]
            )
            for mode, name in MODE_NAMES.items()
        ],
        widths="equal",
        align="start",
        gap=2,
    )
    mo.vstack(
        [
            _summary,
            mo.md("### Rank of each publication that a mode shows"),
            _rows,
            mo.md("### Results"),
            _columns,
        ]
    )
    return


if __name__ == "__main__":
    app.run()
