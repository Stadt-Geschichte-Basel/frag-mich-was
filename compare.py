# /// script
# requires-python = "==3.14.*"
# ///

import marimo

__generated_with = "0.25.2"
app = marimo.App(
    width="full",
    app_title="Suchmodi vergleichen | Frag mich was – Stadt.Geschichte.Basel",
    css_file="sgb.css",
    html_head_file="head-compare.html",
)

with app.setup:
    import html
    import importlib
    import sys
    from collections.abc import Sequence
    from typing import Literal
    from urllib.parse import urlsplit

    import marimo as mo
    from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

    IS_WASM = sys.platform == "emscripten"
    Mode = Literal["semantic", "lexical", "combined"]
    Kind = Literal["specific", "synonyms", "complex", "cross-source"]
    MODE_NAMES: dict[Mode, str] = {
        "semantic": "Semantisch",
        "lexical": "Lexikalisch",
        "combined": "Kombiniert",
    }
    KIND_NAMES = {
        "specific": "Gezielte Suche",
        "synonyms": "Andere Formulierungen",
        "complex": "Erklärende Fragen",
        "cross-source": "Mehrere Quellen",
    }


@app.class_definition
class ReportModel(BaseModel):
    """Reject unexpected report fields.

    >>> ReportModel().model_dump()
    {}
    """

    model_config = ConfigDict(extra="forbid", frozen=True)


@app.function
def safe_source_url(value: str) -> str:
    """Accept canonical publication hosts and reject unsafe links.

    >>> safe_source_url("https://doi.org/10.1/example")
    'https://doi.org/10.1/example'
    >>> safe_source_url("javascript:alert(1)")
    Traceback (most recent call last):
    ValueError: Invalid publication URL.
    """
    parts = urlsplit(value)
    if (
        parts.scheme != "https"
        or parts.hostname not in {"doi.org", "storymaps.arcgis.com"}
        or parts.username is not None
        or parts.password is not None
        or value != value.strip()
        or any(ord(char) < 32 for char in value)
    ):
        raise ValueError("Invalid publication URL.")
    return value


@app.class_definition
class PublicationRanks(ReportModel):
    """The ranks of one publication.

    >>> PublicationRanks(title="A", key="https://doi.org/10.1/a", semantic=1).lexical is None
    True
    """

    title: str = Field(min_length=1)
    key: str
    semantic: int | None = Field(default=None, gt=0)
    lexical: int | None = Field(default=None, gt=0)
    combined: int | None = Field(default=None, gt=0)
    _url = field_validator("key")(safe_source_url)


@app.class_definition
class DisplayPassage(ReportModel):
    """A result excerpt without an embedding.

    >>> DisplayPassage(title="A", text="Text", url="https://doi.org/10.1/a").content_type
    'chapter'
    """

    title: str = Field(min_length=1)
    text: str = Field(min_length=1)
    url: str
    content_type: Literal["chapter", "data_story"] = "chapter"
    coverage: Literal["full_text", "summary"] = "full_text"
    _url = field_validator("url")(safe_source_url)


@app.class_definition
class QueryReport(ReportModel):
    """The saved display data for one query.

    >>> QueryReport.model_fields["query"].is_required()
    True
    """

    query: str = Field(min_length=1)
    topic: str = Field(min_length=1)
    kind: Kind
    expected: list[PublicationRanks]
    semantic: list[DisplayPassage] = Field(max_length=5)
    lexical: list[DisplayPassage] = Field(max_length=5)
    combined: list[DisplayPassage] = Field(max_length=5)

    @model_validator(mode="after")
    def expected_sources(self) -> QueryReport:
        """Require distinct expected sources.

        >>> callable(QueryReport.expected_sources)
        True
        """
        keys = [row.key for row in self.expected]
        if not keys or len(set(keys)) != len(keys):
            raise ValueError("Expected sources must be nonempty and distinct.")
        return self


@app.class_definition
class SummaryRow(ReportModel):
    """The number of queries of a group that a mode answers completely.

    >>> SummaryRow.model_fields["complete3"].is_required()
    True
    """

    kind: Literal["all", "specific", "synonyms", "complex", "cross-source"]
    mode: Mode
    queries: int = Field(gt=0)
    complete3: int = Field(ge=0)
    complete5: int = Field(ge=0)


@app.class_definition
class ComparisonReport(ReportModel):
    """The versioned I/O contract of the comparison report.

    >>> ComparisonReport.model_fields["schema_version"].default
    1
    """

    schema_version: Literal[1] = 1
    queries: list[QueryReport] = Field(min_length=1)
    summary: list[SummaryRow] = Field(min_length=1)


@app.function
def format_rank(value: int | None) -> str:
    """Show a missing rank as a dash.

    >>> format_rank(None), format_rank(2)
    ('—', '2')
    """
    return "—" if value is None else str(value)


@app.function
def all_found(query: QueryReport, mode: Mode, limit: int = 3) -> bool:
    """Require every expected publication within the rank limit.

    >>> callable(all_found)
    True
    """
    return all(
        (place := getattr(row, mode)) is not None and place <= limit for row in query.expected
    )


@app.function
def filter_queries(queries: Sequence[QueryReport], kind: str = "all") -> list[QueryReport]:
    """Select the saved queries of one type while preserving their order.

    >>> filter_queries([])
    []
    """
    return [query for query in queries if kind == "all" or query.kind == kind]


@app.function
def table_html(headers: Sequence[str], rows: Sequence[Sequence[str]], caption: str) -> str:
    """Render a labelled table and escape all cell values.

    >>> "&lt;script&gt;" in table_html(["Titel"], [["<script>"]], "Tabelle")
    True
    """
    head = "".join(f'<th scope="col">{html.escape(value)}</th>' for value in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{html.escape(value)}</td>" for value in row) + "</tr>"
        for row in rows
    )
    return (
        f'<div class="sgb-table-scroll" role="region" aria-label="{html.escape(caption, quote=True)}" tabindex="0">'
        f'<table class="sgb-table"><caption>{html.escape(caption)}</caption><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}</tbody></table></div>"
    )


@app.function
def expected_html(query: QueryReport) -> str:
    """Link each expected source with its individual ranks.

    >>> callable(expected_html)
    True
    """
    items = []
    for row in query.expected:
        ranks = " · ".join(
            f"{name}: {format_rank(getattr(row, mode))}" for mode, name in MODE_NAMES.items()
        )
        items.append(
            f'<li><a href="{html.escape(row.key, quote=True)}" target="_blank" rel="noopener noreferrer">'
            f"{html.escape(row.title)}</a><br>{ranks}</li>"
        )
    return '<ul class="sgb-expected">' + "".join(items) + "</ul>"


@app.function
def results_html(passages: Sequence[DisplayPassage]) -> str:
    """Escape every excerpt value before rendering result cards.

    >>> results_html([])
    '<p role="status">Keine Textstelle gefunden.</p>'
    """
    items = []
    for passage in passages:
        label = (
            "Originalstory öffnen"
            if passage.content_type == "data_story"
            else "Originalkapitel öffnen"
        )
        coverage = (
            "<p><small>Nur Zusammenfassung</small></p>" if passage.coverage == "summary" else ""
        )
        items.append(
            f'<li><h3>{html.escape(passage.title)}</h3><small><a href="{html.escape(passage.url, quote=True)}" '
            f'target="_blank" rel="noopener noreferrer">{label}</a></small>{coverage}'
            f"<p>{html.escape(passage.text)}</p></li>"
        )
    if not items:
        return '<p role="status">Keine Textstelle gefunden.</p>'
    return '<ol class="sgb-results" role="list">' + "".join(items) + "</ol>"


@app.function
def summary_html(rows: Sequence[SummaryRow]) -> str:
    """Show the number of complete queries for each type and mode.

    >>> callable(summary_html)
    True
    """
    return table_html(
        ["Fragetyp", "Suchmodus", "Fragen", "Vollständig@3", "Vollständig@5"],
        [
            [
                "Alle Fragen" if row.kind == "all" else KIND_NAMES[row.kind],
                MODE_NAMES[row.mode],
                str(row.queries),
                f"{row.complete3} von {row.queries}",
                f"{row.complete5} von {row.queries}",
            ]
            for row in rows
        ],
        "Ergebnisse nach Fragetyp",
    )


@app.function
def catalogue_html(queries: Sequence[QueryReport]) -> str:
    """Show every expected-source rank in the publication order.

    >>> callable(catalogue_html)
    True
    """
    return table_html(
        ["Suchanfrage", "Fragetyp", "Thema", "Erwartete Publikationen", *MODE_NAMES.values()],
        [
            [
                query.query,
                KIND_NAMES[query.kind],
                query.topic,
                " / ".join(row.title for row in query.expected),
                *(
                    ", ".join(format_rank(getattr(row, mode)) for row in query.expected)
                    + (" ✓" if all_found(query, mode) else " ✗")
                    for mode in MODE_NAMES
                ),
            ]
            for query in queries
        ],
        "Beispielfragen und Quellenränge",
    )


@app.function
def native_report() -> ComparisonReport:
    """Build the same report for a local notebook session.

    >>> callable(native_report)
    True
    """
    # Resolve optional native helpers only when a local session calls this function.
    # A static import makes the WASM exporter bundle build tools into local wheels.
    builder = importlib.import_module("scripts.comparison_report").build_report
    return ComparisonReport.model_validate_json(builder().model_dump_json())


@app.cell
def _():
    mo.Html("""
    <header class="sgb-brand">
    <a href="https://stadtgeschichtebasel.ch/" aria-label="Stadt.Geschichte.Basel: zum Portal">
    <img src="public/sgb/assets/img/logo.svg" alt="Stadt.Geschichte.Basel" width="180" height="79">
    </a><a class="sgb-portal" href="./">Zur Suche</a>
    </header>
    """)
    return


@app.cell
async def _():
    report: ComparisonReport | None = None
    try:
        if IS_WASM:
            from pyodide.http import pyfetch  # ty: ignore[import-not-found]

            _base = mo.notebook_location()
            if _base is None:
                raise ValueError("Unknown notebook location")
            _response = await pyfetch(str(_base.joinpath("public", "comparison.json")))
            if not _response.ok:
                raise ValueError(f"HTTP {_response.status}")
            report = ComparisonReport.model_validate_json(await _response.string())
        else:
            report = native_report()
    except Exception:
        mo.output.replace(
            mo.Html(
                '<div role="alert"><strong>Der Vergleich ist nicht verfügbar.</strong> '
                "Lade die Seite neu. Wenn das nicht hilft, versuche es später nochmals.</div>"
            )
        )
    return (report,)


@app.cell
def _(report):
    mo.stop(report is None)
    mo.md(f"""
    # Suchmodi vergleichen

    Wie unterscheiden sich **Semantisch**, **Lexikalisch** und **Kombiniert**?
    Vergleiche {len(report.queries)} Beispielfragen aus allen neun Forschungsbänden und sieben Data Stories.
    Die Fragen enthalten genaue Begriffe, Synonyme und komplexere Zusammenhänge.
    Vier Fragen beziehen sich auf jeweils zwei Publikationen.

    Die Ergebnisse wurden beim Erstellen der Seite berechnet.
    Du kannst die Beispiele ohne Download des Sprachmodells erkunden.
    Erwartete Quellen sind passende Beispiele. Auch andere Treffer können relevant sein.
    Die Textstellen sind keine geprüften Antworten. Prüfe ihren Zusammenhang in der Originalpublikation.
    """)
    return


@app.cell
def _(report):
    mo.stop(report is None)
    # These statements describe the saved examples. A test checks them against the report.
    mo.Html(
        """
    <section class="sgb-insights" aria-labelledby="comparison-insights">
    <h2 id="comparison-insights">Was der Vergleich zeigt</h2>
    <ul>
    <li><strong>Gezielte Suchanfragen führen zuverlässig zur Quelle.</strong>
    Alle drei Suchmodi finden bei Namen, Orten, Jahreszahlen und Fachbegriffen die erwartete Publikation.</li>
    <li><strong>Die Wortwahl macht einen Unterschied.</strong>
    Bei anderen Formulierungen findet «Lexikalisch» die erwartete Quelle deutlich seltener
    als «Semantisch» und «Kombiniert».</li>
    <li><strong>Kombiniert verbessert nicht jede Anfrage.</strong>
    Bei der Frage zu Schweizerhalle rückt die erwartete Quelle von Rang 2 in der semantischen Suche
    auf Rang 8 in der kombinierten Suche.</li>
    <li><strong>Bei mehreren Quellen zählt die Vollständigkeit.</strong>
    «Kombiniert» findet beide erwarteten Quellen am häufigsten unter den ersten fünf Treffern.</li>
    </ul>
    <p>Die Aussagen gelten für diese Beispiele. Die Tabelle unten zeigt die Zahlen.</p>
    </section>
    """
    )
    return


@app.cell
def _(report):
    mo.stop(report is None)
    mo.vstack(
        [
            mo.md("""
        ## Ergebnisse nach Fragetyp

        **Vollständig@3** zählt Fragen, bei denen alle erwarteten Quellen unter den ersten drei Treffern stehen.
        **Vollständig@5** zählt Fragen, bei denen alle erwarteten Quellen unter den ersten fünf Treffern stehen.
        Eine von zwei Quellen genügt nicht.

        Die Beispiele zeigen auch Fälle, bei denen Quellen fehlen oder weiter hinten stehen.
        """),
            mo.Html(summary_html(report.summary)),
        ]
    )
    return


@app.cell
def _(report):
    mo.stop(report is None)
    kind_filter = mo.ui.dropdown(
        options={
            "Alle": "all",
            **{
                label: kind
                for kind, label in KIND_NAMES.items()
                if any(query.kind == kind for query in report.queries)
            },
        },
        value="Alle",
        label="Fragetyp",
    )
    mo.vstack([mo.md("## Beispielfragen"), kind_filter])
    return (kind_filter,)


@app.cell
def _(kind_filter, report):
    mo.stop(report is None)
    filtered = filter_queries(report.queries, kind_filter.value)
    picker = mo.ui.dropdown(
        options={query.query: number for number, query in enumerate(filtered)},
        value=filtered[0].query,
        label="Beispielfrage",
        full_width=True,
    )
    mo.vstack(
        [
            mo.md(f"""
        **{len(filtered)} Fragen passen zum Filter.**
        Die Ränge folgen der Reihenfolge der erwarteten Publikationen.
        Ein Häkchen bedeutet: Alle erwarteten Quellen stehen in den Top 3.
        Ein Strich bedeutet: Der Suchmodus findet diese Quelle nicht.
        """),
            mo.Html(catalogue_html(filtered)),
            mo.md("## Eine Frage in drei Suchmodi"),
            picker,
        ]
    )
    return filtered, picker


@app.cell
def _(filtered, picker):
    _selected = filtered[picker.value]
    mo.vstack(
        [
            mo.md(f"### Erwartete Publikationen\n\n**Suchanfrage:** {_selected.query}"),
            mo.Html(expected_html(_selected)),
            mo.Html(
                '<div class="sgb-comparison-results">'
                + "".join(
                    f'<section aria-label="{name}"><h2>{name}</h2>{results_html(getattr(_selected, mode))}</section>'
                    for mode, name in MODE_NAMES.items()
                )
                + "</div>"
            ),
        ]
    )
    return


@app.cell
def _():
    mo.Html("""
    <footer class="sgb-footer">
    <a href="./">Zur Suche</a>
    <a href="https://stadtgeschichtebasel.ch/">Stadt.Geschichte.Basel</a>
    <a href="https://dokumentation.stadtgeschichtebasel.ch/">Dokumentation</a>
    <a href="https://stadtgeschichtebasel.ch/datenschutzerklaerung">Datenschutz</a>
    <a href="https://stadtgeschichtebasel.ch/barrierefreiheitserklaerung">Barrierefreiheit</a>
    <a href="https://github.com/Stadt-Geschichte-Basel/frag-mich-was">Quellcode</a>
    </footer>
    """)
    return


if __name__ == "__main__":
    app.run()
