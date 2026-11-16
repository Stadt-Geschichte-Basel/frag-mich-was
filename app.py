# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "bm25s==0.3.16",
# ]
# ///

import marimo

__generated_with = "0.25.2"
app = marimo.App(
    width="medium",
    app_title="Frag mich was – Semantische Suche | Stadt.Geschichte.Basel",
    css_file="sgb.css",
    html_head_file="head.html",
)

with app.setup:
    import html
    import math
    import sys
    from collections.abc import Iterable, Sequence
    from dataclasses import dataclass
    from pathlib import Path
    from typing import Any, Literal, cast
    from urllib.parse import urlsplit

    import bm25s
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
    # Reciprocal Rank Fusion: a publication scores the sum of 1 / (RRF_K + rank), with ranks from 1.
    RRF_K = 60
    Mode = Literal["combined", "lexical", "semantic"]
    # The labels that the mode control shows, with the mode that each selects.
    MODES: dict[str, Mode] = {
        "Kombiniert": "combined",
        "Lexikalisch": "lexical",
        "Semantisch": "semantic",
    }
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
        return parts.hostname in APPROVED_URL_HOSTS or (
            parts.hostname == "storymaps.arcgis.com"
            and parts.username is None
            and parts.password is None
            and parts.netloc == "storymaps.arcgis.com"
            and len(parts.path.removeprefix("/stories/")) == 32
            and parts.path.startswith("/stories/")
            and all(char in "0123456789abcdef" for char in parts.path[9:])
            and not parts.query
            and not parts.fragment
        )
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
    content_type: Literal["chapter", "data_story"] = "chapter"
    coverage: Literal["full_text", "summary"] = "full_text"
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
def best_per_publication(
    scored: Iterable[tuple[Chunk, float]], top_k: int | None = TOP_K
) -> list[tuple[Chunk, float]]:
    """Return each publication’s best passage, best first. Break a score tie by chunk ID.

    A publication is ``chunk.url or chunk.id``. Pass ``top_k=None`` to keep every publication.

    >>> a = Chunk(id="a", title="A", text="x", source="a.md", url="u", embedding=[1.0])
    >>> b = Chunk(id="b", title="A", text="y", source="a.md", url="u", embedding=[1.0])
    >>> c = Chunk(id="c", title="C", text="z", source="c.md", embedding=[1.0])
    >>> [(chunk.id, score) for chunk, score in best_per_publication([(b, 1.0), (a, 1.0), (c, 2.0)])]
    [('c', 2.0), ('a', 1.0)]
    >>> len(best_per_publication([(a, 1.0), (c, 2.0)], top_k=1))
    1
    """
    ordered = sorted(scored, key=lambda pair: (-pair[1], pair[0].id))
    distinct: dict[str, tuple[Chunk, float]] = {}
    for chunk, score in ordered:
        distinct.setdefault(chunk.url or chunk.id, (chunk, score))
    return list(distinct.values())[:top_k]


@app.function
def rank(
    query: Sequence[float], chunks: Sequence[Chunk], top_k: int | None = TOP_K
) -> list[tuple[Chunk, float]]:
    """Return each publication’s best passage by dot product. Break a tie by chunk ID.

    The vectors have unit length, so the dot product is the cosine similarity.

    >>> a = Chunk(id="a", title="A", text="x", source="a.md", embedding=[1.0, 0.0])
    >>> b = Chunk(id="b", title="B", text="y", source="b.md", embedding=[0.0, 1.0])
    >>> [(chunk.id, value) for chunk, value in rank([0.0, 1.0], [a, b])]
    [('b', 1.0), ('a', 0.0)]
    """
    return best_per_publication(
        ((chunk, math.sumprod(query, chunk.embedding)) for chunk in chunks), top_k
    )


@app.function
def lexical_tokens(texts: Sequence[str]) -> list[list[str]]:
    """Split each text into lowercase words. Drop German stopwords. Do not stem.

    The index and each query use this function, so that both sides split words alike.

    >>> lexical_tokens(["Der Rhein und 1501 in Basel.", "und der"])
    [['rhein', '1501', 'basel'], []]
    """
    # With return_ids=False, bm25s returns one list of words for each text.
    return cast(
        list[list[str]],
        bm25s.tokenize(
            list(texts), stopwords="de", lower=True, return_ids=False, show_progress=False
        ),
    )


@app.class_definition
@dataclass(frozen=True)
class LexicalIndex:
    """A BM25 index with the passages in the order of its documents.

    >>> a = Chunk(id="a", title="Basel", text="Der Rhein.", source="a.md", embedding=[1.0])
    >>> LexicalIndex(bm25s.BM25(), (a,)).chunks == (a,)
    True
    """

    retriever: bm25s.BM25
    chunks: tuple[Chunk, ...]


@app.function
def build_lexical_index(chunks: Sequence[Chunk]) -> LexicalIndex:
    """Index the title and the text of each passage.

    >>> a = Chunk(id="a", title="Basel", text="Der Rhein.", source="a.md", embedding=[1.0])
    >>> build_lexical_index([a]).chunks == (a,)
    True
    """
    retriever = bm25s.BM25()
    retriever.index(
        lexical_tokens([f"{chunk.title}\n{chunk.text}" for chunk in chunks]), show_progress=False
    )
    return LexicalIndex(retriever, tuple(chunks))


@app.function
def lexical_rank(
    lexical: LexicalIndex, query: str, top_k: int | None = TOP_K
) -> list[tuple[Chunk, float]]:
    """Return each publication’s best passage by BM25 score. Skip passages with no match.

    An empty, stopword-only, or unknown query matches nothing.

    >>> a = Chunk(id="a", title="Basel", text="Der Rhein.", source="a.md", embedding=[1.0])
    >>> b = Chunk(id="b", title="Bern", text="Die Aare.", source="b.md", embedding=[1.0])
    >>> index = build_lexical_index([a, b])
    >>> [chunk.id for chunk, _ in lexical_rank(index, "Rhein")]
    ['a']
    >>> lexical_rank(index, "der die das")
    []
    """
    tokens = lexical_tokens([query])[0]
    if not tokens:
        return []
    scores = lexical.retriever.get_scores(tokens)
    matches = (
        (chunk, float(score))
        for chunk, score in zip(lexical.chunks, scores, strict=True)
        if score > 0
    )
    return best_per_publication(matches, top_k)


@app.function
def fuse(
    semantic: Sequence[tuple[Chunk, float]],
    lexical: Sequence[tuple[Chunk, float]],
    top_k: int | None = TOP_K,
) -> list[tuple[Chunk, float]]:
    """Combine two complete publication rankings with Reciprocal Rank Fusion.

    Each ranking lists a publication once, best first. A publication scores the sum of
    ``1 / (60 + rank)`` over the rankings that contain it. Ranks start at 1.
    The passage comes from the ranking with the better rank. The semantic passage wins a tie.
    A score tie breaks by the ID of the chosen passage. The result is cut to ``top_k``.

    >>> a = Chunk(id="a", title="A", text="x", source="a.md", embedding=[1.0])
    >>> b = Chunk(id="b", title="B", text="y", source="b.md", embedding=[1.0])
    >>> [(chunk.id, round(score, 4)) for chunk, score in fuse([(a, 0.9), (b, 0.5)], [(b, 3.0)])]
    [('b', 0.0325), ('a', 0.0164)]
    """
    scores: dict[str, float] = {}
    # The better rank wins. At equal rank, the earlier ranking (semantic) wins.
    passages: dict[str, tuple[int, int, Chunk]] = {}
    for order, ranking in enumerate((semantic, lexical)):
        for position, (chunk, _score) in enumerate(ranking, start=1):
            key = chunk.url or chunk.id
            scores[key] = scores.get(key, 0.0) + 1 / (RRF_K + position)
            if key not in passages or (position, order) < passages[key][:2]:
                passages[key] = (position, order, chunk)
    fused = [(passages[key][2], score) for key, score in scores.items()]
    fused.sort(key=lambda pair: (-pair[1], pair[0].id))
    return fused[:top_k]


@app.function
def search(
    mode: Mode, query: str, vector: Sequence[float] | None, lexical: LexicalIndex
) -> list[tuple[Chunk, float]]:
    """Return up to five distinct publications for the query in the chosen mode.

    The semantic and combined modes need the query vector. The lexical mode does not.

    >>> a = Chunk(id="a", title="Basel", text="Der Rhein.", source="a.md", embedding=[1.0])
    >>> index = build_lexical_index([a])
    >>> [chunk.id for chunk, _ in search("lexical", "Rhein", None, index)]
    ['a']
    >>> [chunk.id for chunk, _ in search("semantic", "Rhein", [1.0], index)]
    ['a']
    >>> [chunk.id for chunk, _ in search("combined", "Rhein", [1.0], index)]
    ['a']
    >>> search("combined", "Rhein", None, index)
    Traceback (most recent call last):
    ValueError: The combined mode needs a query vector.
    """
    if mode == "lexical":
        return lexical_rank(lexical, query)
    if vector is None:
        raise ValueError(f"The {mode} mode needs a query vector.")
    semantic = rank(vector, lexical.chunks, None)
    if mode == "semantic":
        return semantic[:TOP_K]
    return fuse(semantic, lexical_rank(lexical, query, None))


@app.function
def corpus_counts(chunks: Sequence[Chunk]) -> tuple[int, int]:
    """Count book volumes and distinct Data Stories separately.

    >>> corpus_counts([])
    (0, 0)
    """
    volumes = {chunk.source[4:6] for chunk in chunks if chunk.content_type == "chapter"}
    stories = {chunk.url for chunk in chunks if chunk.content_type == "data_story"}
    return len(volumes), len(stories)


@app.function
def render_results(results: Sequence[tuple[Chunk, float]]) -> str:
    """Render ranked passages as HTML. Escape every value that comes from the index.

    >>> chunk = Chunk(id="a", title="<A>", text="x & y", source="a.md", embedding=[1.0])
    >>> render_results([(chunk, 0.5)])
    '<p role="status" aria-atomic="true">1 passende Publikationen gefunden.</p><ol class="sgb-results" role="list"><li><h2>&lt;A&gt;</h2><p>x &amp; y</p></li></ol>'
    >>> render_results([])
    '<p role="status" aria-atomic="true">Keine Textstelle gefunden.</p>'
    """
    if not results:
        return '<p role="status" aria-atomic="true">Keine Textstelle gefunden.</p>'
    items: list[str] = []
    for chunk, _score in results:
        link = ""
        label = (
            "Originalstory öffnen"
            if chunk.content_type == "data_story"
            else "Originalkapitel öffnen"
        )
        coverage = (
            "<p><small>Nur Zusammenfassung</small></p>" if chunk.coverage == "summary" else ""
        )
        if chunk.url is not None:
            href = html.escape(chunk.url, quote=True)
            link = (
                f'<small><a href="{href}" target="_blank" rel="noopener noreferrer" '
                f'aria-label="{label}: {html.escape(chunk.title, quote=True)}">'
                f"{label}</a></small>"
            )
        items.append(
            f"<li><h2>{html.escape(chunk.title)}</h2>{link}{coverage}<p>{html.escape(chunk.text)}</p></li>"
        )
    return (
        f'<p role="status" aria-atomic="true">{len(results)} passende Publikationen gefunden.</p>'
        f'<ol class="sgb-results" role="list">{"".join(items)}</ol>'
    )


@app.cell
def _():
    mo.md("""
    <header class="sgb-brand">
    <a href="https://stadtgeschichtebasel.ch/" aria-label="Stadt.Geschichte.Basel: zum Portal">
    <img src="public/sgb/assets/img/logo.svg" alt="Stadt.Geschichte.Basel" width="180" height="79">
    </a>
    <a class="sgb-portal" href="https://stadtgeschichtebasel.ch/">Zum Portal</a>
    </header>

    # Frag mich was

    **Lexikalische und semantische Suche für Basels Geschichte.**

    Finde passende Textstellen und öffne die Originalpublikationen.
    """)
    return


@app.cell
async def _():
    index: SearchIndex | None = None
    index_error = ""
    try:
        mo.output.replace(mo.Html('<p role="status">Die Suche wird vorbereitet.</p>'))
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
    mo.output.clear()
    return index, index_error


@app.cell
def _(index, index_error):
    if index is None:
        _status = mo.callout(
            mo.Html(
                '<div role="alert"><strong>Die Suche ist nicht verfügbar.</strong> '
                "Lade die Seite neu. Wenn das nicht hilft, versuche es später nochmals.</div>"
            ),
            kind="danger",
        )
    elif not index.chunks:
        _status = mo.callout(
            mo.Html(
                '<p role="status">Zurzeit sind keine Publikationen verfügbar. Versuche es später nochmals.</p>'
            ),
            kind="warn",
        )
    else:
        _volumes, _stories = corpus_counts(index.chunks)
        _status = mo.Html(
            f'<p class="sgb-corpus" role="status">{_volumes} '
            '<a href="https://emono.unibas.ch/stadtgeschichtebasel/catalog">Forschungsbände</a> '
            f'und {_stories} <a href="https://stadtgeschichtebasel.ch/data-stories">Data Stories</a> '
            "durchsuchen.</p>"
        )
    _status
    return


@app.cell
def _(index):
    mo.stop(index is None or not index.chunks)
    form = mo.ui.text(
        label="Wonach suchst du in Basels Geschichte?",
        placeholder="Rhein und Handel in Basel",
        full_width=True,
    ).form(submit_button_label="Suchen", bordered=False)
    retry = mo.ui.run_button(label="Erneut versuchen")
    form
    return form, retry


@app.cell
def _(index):
    mo.stop(index is None or not index.chunks)
    # The control sits outside the form. A change of mode runs the search again with the
    # query that the form last submitted.
    # marimo names the radio group "Radio Group". The fieldset gives the options a real name.
    # The options stack, so that they reflow at 320 pixels and with large text.
    mode = mo.ui.radio(options=MODES, value="Kombiniert")
    mo.Html(f'<fieldset class="sgb-mode"><legend>Suchmodus</legend>{mode}</fieldset>')
    return (mode,)


@app.cell
def _(index):
    mo.stop(index is None or not index.chunks)
    lexical = build_lexical_index(index.chunks)
    return (lexical,)


@app.cell
def _():
    # Holds the JavaScript embedding function, so that each search uses the same model instance.
    # It also holds the last successful query with its vector. A change of mode reuses them.
    session: dict[str, Any] = {}
    return (session,)


@app.cell
async def _(form, index, lexical, mode, retry, session):
    retry.value  # A click on Retry runs this cell again.
    mo.stop(form.value is None)
    _query = (form.value or "").strip()
    mo.stop(
        not _query,
        mo.Html('<p role="status">Gib ein Thema oder eine Frage ein. Wähle dann «Suchen».</p>'),
    )
    _mode: Mode = mode.value
    _vector = None
    if _mode != "lexical":
        if session.get("query") == _query:
            _vector = session["vector"]
        else:
            mo.stop(
                _mode == "semantic" and not IS_WASM,
                mo.callout(
                    mo.md(
                        "Die semantische Suche benötigt die WebAssembly-Version. "
                        "Öffne die veröffentlichte Webseite."
                    ),
                    kind="warn",
                ),
            )
            try:
                if IS_WASM:
                    if "embed" not in session:
                        mo.output.replace(
                            mo.Html(
                                '<p role="status">Die erste Suche wird vorbereitet. '
                                "Dafür laden wir etwa 120 MB herunter. "
                                "Das kann einen Moment dauern.</p>"
                            )
                        )
                        from pyodide.code import run_js  # ty: ignore[import-not-found]

                        session["embed"] = await run_js(EMBEDDER_JS)(
                            TRANSFORMERS_JS_URL,
                            index.model.query_model,
                            index.model.query_revision,
                            QUERY_DTYPE,
                        )
                    mo.output.replace(mo.Html('<p role="status">Suche läuft.</p>'))
                    _vector = (await session["embed"](index.model.query_prefix + _query)).to_py()
                    check_vector(_vector, index.model.dimensions)
                    session["query"] = _query
                    session["vector"] = _vector
            except Exception:
                _vector = None
    _failed = _mode != "lexical" and _vector is None
    _parts: list[Any] = []
    if _failed and _mode == "semantic":
        _parts.append(
            mo.callout(
                mo.Html(
                    '<div role="alert"><strong>Die Suche ist fehlgeschlagen.</strong> '
                    "Prüfe deine Internetverbindung und wähle «Erneut versuchen». "
                    "Die lexikalische Suche braucht das Sprachmodell nicht.</div>"
                ),
                kind="danger",
            )
        )
        _parts.append(retry)
    else:
        if _failed:
            _parts.append(
                mo.callout(
                    mo.Html(
                        '<div role="status"><strong>Das Sprachmodell ist nicht verfügbar.</strong> '
                        "Die Ergebnisse stammen nur aus der lexikalischen Suche. "
                        "Prüfe deine Internetverbindung und wähle «Erneut versuchen».</div>"
                    ),
                    kind="warn",
                )
            )
            _parts.append(retry)
        _parts.append(
            mo.md(
                "Die Ergebnisse sind Textauszüge aus den Originalpublikationen, "
                "keine generierten Antworten."
            )
        )
        _results = search("lexical" if _failed else _mode, _query, _vector, lexical)
        _parts.append(mo.Html(render_results(_results)))
    mo.output.replace(mo.vstack(_parts))
    return


@app.cell
def _():
    mo.Html("""
    <details class="sgb-about">
    <summary>Über die Suche</summary>
    <p>Frag mich was ist eine Suchmaschine für die Forschungsbände
    von Stadt.Geschichte.Basel / Christoph Merian Verlag und sieben Data Stories.
    Sie durchsucht die Kapitel einschliesslich der Einleitungen sowie die Erzähltexte
    der Data Stories. Die Anhänge mit Verzeichnissen und «Das jüdische Basel» sind nicht enthalten.
    Alle Data Stories tragen den gemeinsamen Bandtitel «Data Stories».</p>
    <p>Du kannst unter «Suchmodus» zwischen drei Modi wählen.
    «Kombiniert» ist voreingestellt. Dieser Modus führt die lexikalische und die semantische Suche zusammen.
    «Lexikalisch» findet Wörter, Namen und Jahreszahlen so, wie sie in den Texten stehen.
    Er findet nur ganze Wörter in derselben Form und braucht kein Sprachmodell.
    «Semantisch» vergleicht die Bedeutung deiner Eingabe mit den Textstellen.
    Die Reihenfolge beruht dann auf sprachlicher Ähnlichkeit.
    Wenn du den Modus wechselst, bleibt deine Eingabe erhalten.</p>
    <p>Die Suche kann wichtige Stellen übersehen oder unpassende Stellen anzeigen.
    Die Textstellen sind keine geprüften Antworten auf deine Eingabe.
    Prüfe die Aussage und ihren Zusammenhang in der Originalpublikation.</p>
    <p>Deine Eingabe wird lokal in deinem Browser verarbeitet und bleibt auf deinem Gerät.
    Beim ersten Besuch braucht die Seite eine Internetverbindung.
    Die erste Suche in den Modi «Kombiniert» und «Semantisch» lädt ein Sprachmodell von etwa 120 MB herunter.
    Die lexikalische Suche braucht diesen Download nicht.
    Wenn das Sprachmodell nicht lädt, zeigt «Kombiniert» nur lexikalische Ergebnisse.
    Die Links «Originalkapitel öffnen» führen über die DOI zur jeweiligen Publikation.
    «Originalstory öffnen» führt zur Data Story auf ArcGIS StoryMaps.
    «Nur Zusammenfassung» kennzeichnet Ergebnisse, die nur eine Beschreibung durchsuchen.</p>
    <p>Die Buchreihe findest du im
    <a href="https://emono.unibas.ch/stadtgeschichtebasel/catalog">Publikationskatalog</a>.
    Die <a href="https://stadtgeschichtebasel.ch/data-stories">Data Stories</a> findest du im Portal.</p>
    <p>Buchkapitel: © Stadt.Geschichte.Basel / Christoph Merian Verlag,
    <a href="https://creativecommons.org/licenses/by-nc/4.0/">CC BY-NC 4.0</a>.
    Die Erzähltexte der Data Stories sind mit Erlaubnis enthalten.
    Für sie gelten die Rechtehinweise der jeweiligen Originalpublikation.
    Den <a href="https://github.com/Stadt-Geschichte-Basel/frag-mich-was">Quellcode</a>
    findest du auf GitHub. Die Software steht unter AGPL-3.0.</p>
    </details>
    """)
    return


@app.cell
def _():
    mo.Html("""
    <footer class="sgb-footer">
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
