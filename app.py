import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium", app_title="Frag mich was")

with app.setup:
    import html
    import math
    import sys
    from collections.abc import Sequence
    from pathlib import Path
    from typing import Any, Literal
    from urllib.parse import urlsplit

    import marimo as mo
    from pydantic import (
        BaseModel,
        ConfigDict,
        Field,
        FiniteFloat,
        ValidationError,
        field_validator,
        model_validator,
    )

    # Pinned browser runtime for query embeddings. The model ID and revision come from the index.
    TRANSFORMERS_JS_URL = "https://cdn.jsdelivr.net/npm/@huggingface/transformers@4.3.2"
    QUERY_DTYPE = "q8"

    INDEX_PATH = ("public", "embeddings.json")
    TOP_K = 5
    NORM_TOLERANCE = 0.01
    APPROVED_URL_HOSTS = frozenset({"doi.org"})
    IS_WASM = sys.platform == "emscripten"

    # The only JavaScript in the application: load the model, embed one text, return a plain array.
    # The text is an argument. The source below is a constant; no value is interpolated into it.
    EMBEDDER_JS = """
    (async (moduleUrl, modelId, revision, dtype) => {
      const { pipeline } = await import(moduleUrl);
      const extractor = await pipeline("feature-extraction", modelId, {
        revision,
        dtype,
        device: "wasm",
      });
      return async (text) => {
        const output = await extractor(text, { pooling: "mean", normalize: true });
        return Array.from(output.data);
      };
    })
    """


@app.function
def is_safe_url(url: str) -> bool:
    """Accept a site-relative link or an https link to an approved host.

    >>> is_safe_url("https://doi.org/10.5281/zenodo.11124720")
    True
    >>> is_safe_url("docs/intro.html")
    True
    >>> is_safe_url("javascript:alert(1)")
    False
    >>> is_safe_url("//example.org/x")
    False
    """
    if not url or url != url.strip() or "\\" in url or any(ord(char) < 32 for char in url):
        return False
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    if parts.scheme == "https":
        return parts.hostname in APPROVED_URL_HOSTS
    return not parts.scheme and not parts.netloc


@app.function
def check_vector(vector: Sequence[float], dimensions: int) -> None:
    """Raise ValueError unless the vector is finite, has the right size, and has unit length.

    >>> check_vector([0.6, 0.8], 2)
    >>> check_vector([1.0, 1.0], 2)
    Traceback (most recent call last):
    ValueError: vector norm 1.4142 is not 1
    """
    if len(vector) != dimensions:
        raise ValueError(f"vector has {len(vector)} dimensions, expected {dimensions}")
    norm = math.hypot(*vector)
    if not math.isfinite(norm):
        raise ValueError("vector has a non-finite value")
    if abs(norm - 1.0) > NORM_TOLERANCE:
        raise ValueError(f"vector norm {norm:.4f} is not 1")


@app.class_definition
class ModelInfo(BaseModel):
    """Embedding model settings that the index records.

    >>> ModelInfo(
    ...     document_model="a", document_revision="1", query_model="b", query_revision="2", dimensions=2
    ... ).pooling
    'mean'
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    document_model: str = Field(min_length=1)
    document_revision: str = Field(min_length=1)
    query_model: str = Field(min_length=1)
    query_revision: str = Field(min_length=1)
    dimensions: int = Field(gt=0)
    pooling: Literal["mean"] = "mean"
    normalized: Literal[True] = True
    document_prefix: str = ""
    query_prefix: str = ""


@app.class_definition
class Chunk(BaseModel):
    """One searchable passage with its embedding.

    >>> Chunk(id="a:0001", title="A", text="Text.", source="a.md", embedding=[1.0, 0.0]).url is None
    True
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    text: str = Field(min_length=1)
    source: str = Field(min_length=1)
    url: str | None = None
    embedding: list[FiniteFloat]

    @field_validator("title", "text")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @field_validator("url")
    @classmethod
    def _safe_url(cls, value: str | None) -> str | None:
        if value is not None and not is_safe_url(value):
            raise ValueError("must be a relative link or an https link to an approved host")
        return value


@app.class_definition
class SearchIndex(BaseModel):
    """The contract of ``public/embeddings.json``.

    >>> model = ModelInfo(
    ...     document_model="a", document_revision="1", query_model="b", query_revision="2", dimensions=2
    ... )
    >>> SearchIndex(schema_version=1, model=model, chunks=[]).chunks
    []
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    model: ModelInfo
    chunks: list[Chunk]

    @model_validator(mode="after")
    def _check_chunks(self) -> "SearchIndex":
        seen: set[str] = set()
        for chunk in self.chunks:
            if chunk.id in seen:
                raise ValueError(f"duplicate chunk id {chunk.id!r}")
            seen.add(chunk.id)
            try:
                check_vector(chunk.embedding, self.model.dimensions)
            except ValueError as exc:
                raise ValueError(f"chunk {chunk.id!r}: {exc}") from exc
        return self


@app.function
def load_index(raw: str) -> SearchIndex:
    """Parse and validate the index JSON text. Raise ValueError with a short message.

    >>> load_index('{"schema_version": 2}')
    Traceback (most recent call last):
    ValueError: Invalid search index at schema_version: Input should be 1 (3 problems)
    """
    try:
        return SearchIndex.model_validate_json(raw)
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(part) for part in first["loc"]) or "top level"
        raise ValueError(
            f"Invalid search index at {where}: {first['msg']} ({exc.error_count()} problems)"
        ) from exc


@app.function
def rank(
    query: Sequence[float], chunks: Sequence[Chunk], top_k: int = TOP_K
) -> list[tuple[Chunk, float]]:
    """Return each DOI’s best passage by dot product. Break a tie by chunk ID.

    The vectors have unit length, so the dot product is the cosine similarity.

    >>> a = Chunk(id="a", title="A", text="x", source="a.md", embedding=[1.0, 0.0])
    >>> b = Chunk(id="b", title="B", text="y", source="b.md", embedding=[0.0, 1.0])
    >>> [(chunk.id, value) for chunk, value in rank([0.0, 1.0], [a, b])]
    [('b', 1.0), ('a', 0.0)]
    """
    scored = [(chunk, math.sumprod(query, chunk.embedding)) for chunk in chunks]
    scored.sort(key=lambda pair: (-pair[1], pair[0].id))
    distinct: dict[str, tuple[Chunk, float]] = {}
    for chunk, score in scored:
        distinct.setdefault(chunk.url or chunk.id, (chunk, score))
    return list(distinct.values())[:top_k]


@app.function
def render_results(results: Sequence[tuple[Chunk, float]]) -> str:
    """Render ranked passages as HTML. Escape every value that comes from the index.

    >>> chunk = Chunk(id="a", title="<A>", text="x & y", source="a.md", embedding=[1.0])
    >>> render_results([(chunk, 0.5)])
    '<ol><li><strong>&lt;A&gt;</strong><br><small>Ähnlichkeitswert 0.500</small><p>x &amp; y</p></li></ol>'
    >>> render_results([])
    '<p>Keine Textstelle gefunden.</p>'
    """
    if not results:
        return "<p>Keine Textstelle gefunden.</p>"
    items: list[str] = []
    for chunk, value in results:
        link = ""
        if chunk.url is not None:
            href = html.escape(chunk.url, quote=True)
            link = f' · <a href="{href}" target="_blank" rel="noopener noreferrer">Originalkapitel öffnen</a>'
        items.append(
            f"<li><strong>{html.escape(chunk.title)}</strong>"
            f"<br><small>Ähnlichkeitswert {value:.3f}{link}</small>"
            f"<p>{html.escape(chunk.text)}</p></li>"
        )
    return f"<ol>{''.join(items)}</ol>"


@app.cell
def _():
    mo.md("""
    # Frag mich was

    **Fragen stellen. Geschichte finden.**

    Entdecke Kapitel aus Stadt.Geschichte.Basel mit einer Frage.
    Die Suche läuft lokal im Browser. Deine Frage bleibt auf deinem Gerät.
    Die erste Suche lädt ein Sprachmodell von etwa 120 MB herunter.
    Der Ähnlichkeitswert zeigt die Reihenfolge, keine Wahrscheinlichkeit.

    [Publikationskatalog](https://emono.unibas.ch/stadtgeschichtebasel/catalog)

    Inhalte: CC BY-NC 4.0, © Stadt.Geschichte.Basel / Christoph Merian Verlag.
    [Lizenz](https://creativecommons.org/licenses/by-nc/4.0/) ·
    [Quellcode (AGPL-3.0)](https://github.com/Stadt-Geschichte-Basel/frag-mich-was)
    """)
    return


@app.cell
async def _():
    index: SearchIndex | None = None
    index_error = ""
    try:
        with mo.status.spinner(title="Suchindex wird geladen"):
            _base = mo.notebook_location()
            if _base is None:
                raise ValueError("The notebook location is unknown.")
            _location = _base.joinpath(*INDEX_PATH)
            if IS_WASM:
                from pyodide.http import pyfetch  # ty: ignore[import-not-found]

                _response = await pyfetch(str(_location))
                if not _response.ok:
                    raise ValueError(f"The server answered with status {_response.status}.")
                _raw = await _response.string()
            else:
                _raw = Path(str(_location)).read_text(encoding="utf-8")
            index = load_index(_raw)
    except Exception as _exc:
        index_error = str(_exc) or type(_exc).__name__
    return index, index_error


@app.cell
def _(index, index_error):
    if index is None:
        _status = mo.callout(
            mo.Html(
                "<strong>Die Suche ist nicht verfügbar.</strong> Der Suchindex konnte nicht geladen werden. "
            ),
            kind="danger",
        )
    elif not index.chunks:
        _status = mo.callout(mo.Html("Der Suchindex enthält keine Textstellen."), kind="warn")
    else:
        _works = len({chunk.source for chunk in index.chunks})
        _status = mo.callout(
            mo.Html(
                f"Bereit. Der Index enthält {len(index.chunks)} Textstellen aus {_works} Kapiteln."
            ),
            kind="success",
        )
    _status
    return


@app.cell
def _(index):
    mo.stop(index is None or not index.chunks)
    form = mo.ui.text(
        label="Frage",
        placeholder="Welche Rolle spielte die Rheinfischerei für Basel?",
        full_width=True,
    ).form(submit_button_label="Suchen", bordered=False)
    retry = mo.ui.run_button(label="Erneut versuchen")
    form
    return form, retry


@app.cell
def _():
    # Holds the JavaScript embedding function, so that each search uses the same model instance.
    session: dict[str, Any] = {}
    return (session,)


@app.cell
async def _(form, index, retry, session):
    retry.value  # A click on Retry runs this cell again.
    _query = (form.value or "").strip()
    mo.stop(not _query, mo.md("Stelle eine Frage. Wähle dann **Suchen**."))
    mo.stop(
        not IS_WASM,
        mo.callout(
            mo.md(
                "Die Suche benötigt die WebAssembly-Version. Öffne die veröffentlichte Webseite."
            ),
            kind="warn",
        ),
    )
    try:
        if "embed" not in session:
            with mo.status.spinner(
                title="Sprachmodell wird geladen",
                subtitle="Die erste Suche lädt etwa 120 MB herunter.",
            ):
                from pyodide.code import run_js  # ty: ignore[import-not-found]

                session["embed"] = await run_js(EMBEDDER_JS)(
                    TRANSFORMERS_JS_URL,
                    index.model.query_model,
                    index.model.query_revision,
                    QUERY_DTYPE,
                )
        with mo.status.spinner(title="Suche läuft"):
            _vector = (await session["embed"](index.model.query_prefix + _query)).to_py()
            check_vector(_vector, index.model.dimensions)
            _output = mo.Html(render_results(rank(_vector, index.chunks)))
    except Exception as _exc:
        _output = mo.vstack(
            [
                mo.callout(
                    mo.Html(
                        "<strong>Die Suche ist fehlgeschlagen.</strong> "
                        "Das Sprachmodell konnte nicht geladen oder ausgeführt werden. "
                    ),
                    kind="danger",
                ),
                retry,
            ]
        )
    _output
    return


if __name__ == "__main__":
    app.run()
