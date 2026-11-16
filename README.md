# Frag mich was

**A lexical and semantic search engine for the research volumes and seven Data Stories of Stadt.Geschichte.Basel.**

Search by word, name, date, topic, or question.
The search finds passages with the same words or with a related meaning.
Results link to the original book chapters and Data Stories.
The search retrieves existing passages. It does not generate or verify answers.

The interface uses Swiss Standard German (de-CH).
The corpus contains German-language chapters, including introductions. It excludes appendices.
Source quotations keep their original spelling.
GitHub Pages hosts the static marimo WebAssembly application.
The application has no backend or inference API.

## Search

Enter a topic or question. Select **Suchen**.
For example: “Rhein und Handel in Basel”.
You can also ask: “Welche Bedeutung hatte der Rhein für Basel?”
Related wording can also find relevant passages.

Select a search mode with **Suchmodus**. The control sits below the search form.
It is a native select list. It keeps its label and its keyboard behaviour. Tab reaches it. A letter key selects an option.

| Mode | What it does | Needs the model |
| --- | --- | --- |
| **Semantisch** (default) | Compares the meaning of the query with the passages. | Yes. Without the model, it shows an error and a hint about the lexical mode. |
| **Lexikalisch** | Finds words, names, and dates as the texts spell them. It does not stem words. | No |
| **Kombiniert** | Combines the lexical and the semantic ranking. | Yes. Without the model, it shows lexical results and a notice. |

A mode change keeps the submitted query. The interface reuses the vector of the last successful query.
The text field does not take part in a mode change. Select **Suchen** to submit a new query.
The lexical mode starts no model import and no model download.

Each result shows the publication title, its volume title, an excerpt, and a link to the original.
Chapter links show **Originalkapitel öffnen** and use the DOI.
Story links show **Originalstory öffnen** and open ArcGIS StoryMaps.
All stories use **Data Stories** as their shared volume title.
The page shows up to five distinct publications in one ranking.
A **Nur Zusammenfassung** label marks records that contain only a description.
The seven current story records contain full narrative text.
Results are excerpts, not generated or verified answers.
The interface does not show numeric scores.

**Über die Suche** contains source, publisher, search limitation, privacy, licence, catalog, and source-code information.
The disclosure sits below the search results.

## How it works

1. The importer converts chapter HTML into Markdown files under `content/`.
2. The index builder splits each text into passages of 120 to 180 model tokens.
3. The builder calculates normalized embeddings with the pinned multilingual model.
4. The builder writes passages and embeddings to `public/embeddings.json`.
5. The browser loads and validates the index.
6. The browser builds one BM25 index from the title and text of each passage. It uses `bm25s`, German stopwords, and no stemming. Titles, passages, and queries use the same tokenizer.
7. In the modes **Kombiniert** and **Semantisch**, a quantized ONNX model calculates the query embedding in the browser.
8. Python ranks the passages. Cosine similarity gives the semantic ranking. BM25 gives the lexical ranking. Each ranking keeps each publication's best passage. A publication is `chunk.url or chunk.id`.
9. **Kombiniert** fuses the two complete publication rankings with Reciprocal Rank Fusion. A publication scores `sum(1 / (60 + rank))` with ranks from 1. A publication in one ranking stays in the result. The passage comes from the ranking with the better rank. The semantic passage wins a tie. A score tie breaks by passage ID. The page then shows the top five.

The lexical ranking skips passages with a BM25 score of zero or less.
An empty, stopword-only, or unknown query has no lexical match.

The query stays in the browser. No inference service receives it.
All corpus text and embeddings are public. Do not add confidential or restricted text.

The index size and local parsing measurements appear under **Data Story coverage** below.
Transfer size depends on host compression.
The first search also downloads a model of about 120 MB.
The first visit needs a network connection.
The application does not promise complete offline operation.

The browser installs `bm25s` from PyPI. The export reads the pin `bm25s==0.3.16` from the PEP 723 header of `app.py`. Keep it equal to the pin in `pyproject.toml`. A test checks this.
Runtime and model downloads use `cdn.jsdelivr.net`, `files.pythonhosted.org`, `pypi.org`, `wasm.marimo.app`, and Hugging Face file hosts.
Branding assets load from this site's `public/sgb/` directory.

## Browser and local parity

The browser runs on Pyodide 314.0.0 with Python 3.14. Pyodide supplies `marimo`, `pydantic`, `pydantic_core`, `numpy`, and the other packages from its own lockfile. A pin in the PEP 723 header does not change them.
The local environment must run the same versions. Then the tests and the browser run the same code.

- `.python-version` and `requires-python` select Python 3.14.
- `pyproject.toml` pins `pydantic`, `marimo`, and `bm25s` directly.
- `constraint-dependencies` in `pyproject.toml` pins every other package that the browser and the local environment share. Each pin equals the Pyodide version.
- `bm25s` is the only runtime package from PyPI. Its pin in the header of `app.py` equals its pin in `pyproject.toml`.

`msgspec` differs on purpose. Marimo 0.25.2 needs `msgspec` 0.22 or later in the local environment. The marimo runtime in the browser uses 0.20.0. The app does not use it.

The browser test `test_local_versions_match_the_pyodide_lockfile` compares the pins and the installed packages with the lockfile that the exported site requests. It also compares the Python minor version.
CI does not run it. After a marimo upgrade, update the pins:

1. Run `uv run python -m scripts.export_site`.
2. Run `uv run pytest -m browser --no-cov -k lockfile`. Read the mismatches.
3. Set each pin in `pyproject.toml` to the lockfile version.
4. Run `uv lock`. If a package conflicts with marimo, leave it out of the pins and name it here.
5. Run `uv sync --locked` and the gate.

## Models

| Use | Model | Where to pin |
| --- | --- | --- |
| Passages, at build time | `intfloat/multilingual-e5-small` | `MODEL` in `scripts/build_index.py` |
| Queries, in the browser | `Xenova/multilingual-e5-small`, `q8` | `MODEL` in `scripts/build_index.py`, `QUERY_DTYPE` in `app.py` |
| Browser runtime | Transformers.js | `TRANSFORMERS_JS_URL` in `app.py` |

The index records immutable model revisions, 384 dimensions, normalization, and the E5 prefixes.
The page reads the query model from the index.
The native embedding dependencies stay in the `index` dependency group.

## Lexical search measurements

The development machine measured `bm25s` 0.3.16 on the 6,660 passages of the committed index.
The browser rows run a probe notebook with the committed index in Pyodide. They exclude the wheel download.
The plan allows three seconds to build the index and 200 milliseconds for one query.

| Environment | Import | Tokenize and index | One query |
| --- | --- | --- | --- |
| Native Python 3.14 | 0.08 s | 0.22 s | 0.01 ms |
| Chromium, Pyodide | 0.16 s | 0.37 s | 0.6 ms |
| Firefox, Pyodide | 0.18 s | 0.44 s | 1.0 ms |

The index build and the queries start no thread. Pyodide recorded no `threading.Thread.start` call in either browser.
A test checks this natively.

## Compare the search modes

The notebook `compare.py` compares 44 queries in all three modes.
The published subpage is `vergleich.html`. **Über die Suche** links to it with **Suchmodi vergleichen**.
The page uses Swiss Standard German and the same SGB design as the search. **Zur Suche** returns to the main page.

```bash
uv run marimo edit compare.py                 # Opens the saved examples. No model is needed.
uv run python -m scripts.compare_modes        # Prints the summary.
```

The catalogue covers all nine volumes and all seven Data Stories.
All questions use four search-intent categories:

- **Gezielte Suche:** 18 queries use names, dates, places, or technical terms.
- **Andere Formulierungen:** Nine queries use different words for a topic.
- **Erklärende Fragen:** 13 queries ask about processes, causes, or relationships.
- **Mehrere Quellen:** Four questions span two expected publications each.

`scripts/comparison_queries.py` holds the examples, expected source links, and local source notes.
Paired variants let users compare different words for the same topic.
For example, “Erbleihe, Ehrschatz und Grundzins bei Basler Häusern” has this variant:
“Weshalb mussten Hauseigentümer in Basel Geld an geistliche Institutionen zahlen, obwohl sie ihre Liegenschaften verkaufen konnten?”

The page starts with **Was der Vergleich zeigt**. This text is static.
`tests/test_comparison_report.py` checks that the report still supports each statement.
The conclusions apply to the 44 selected examples.

The notebook shows a summary by query type. A filter selects one query type.
The query table shows the rank of each expected publication. Ranks follow the source order in the table.
A tick requires every expected publication in the top three. A dash means that the mode skips a publication.
The selected query shows linked expected sources, individual ranks, and all three result lists side by side.
Narrow screens stack the result lists. Tables wrap long questions and publication titles.

**Vollständig@k** counts queries with every expected source in the first k results.
A question with one of its two sources retrieved does not count as complete.
The summary reports the first three and the first five results.

Expected sources identify supported publications. Other results can also be relevant. The catalogue is not an exhaustive relevance judgement.

The committed index and vectors gave these results on 2026-11-16:

| Mode | Vollständig@3 | Vollständig@5 |
| --- | --- | --- |
| Semantisch | 38 of 44 | 40 of 44 |
| Lexikalisch | 31 of 44 | 34 of 44 |
| Kombiniert | 38 of 44 | 41 of 44 |

All modes find the 18 targeted queries in the top three.
For alternative wording, semantic and combined modes each find eight of nine. Lexical search finds four.
For explanatory questions, semantic and combined search each find eleven of thirteen. Lexical search finds nine.
For cross-source questions in the top five, combined search completes three of four queries. Semantic search completes two. Lexical search completes one.
These examples show that combined search can lower a source's rank.
The Schweizerhalle paraphrase ranks its expected source second semantically and eighth in combined mode.

Eight established queries keep their regression checks. The public page classifies them by search intent, like every other query.
The other examples have no retrieval success threshold.
They check source evidence, vectors, the summary, the filter, and agreement with the application.
`scripts/compare_modes.py` holds the comparison logic. `tests/test_compare.py` checks it.
Model-enabled tests reproduce every new query vector with the pinned Python model.
Browser tests check both pages, navigation, the filter, source links, failure messages, and narrow layouts in Chromium and Firefox.

After a catalogue change, regenerate the fixture:

```bash
uv run --locked --group index python -m scripts.build_index --fixtures-only
```

This command preserves the passage index. The full index build also generates the comparison vectors.

The site export calculates all saved rankings with the committed index and vectors.
It writes the validated report to `dist/public/comparison.json` and exports the comparison to `dist/vergleich.html`.
The report contains query types, summaries, source ranks, and result excerpts. It contains no embeddings.
The browser validates the report with Pydantic and uses `pyfetch` to load it.
The published page downloads neither the search index nor an embedding model.
The comparison uses only the standard library, marimo, and Pydantic in the browser. Local helpers load only in native sessions. The export rejects bundled local Python wheels.

Both pages share the existing assets. CI requires both HTML files and the report before it uploads the Pages artifact.
Production deployment follows the existing workflow on `main` after the PR is merged.

Run the repository gate after generation. Commit the catalogue and generated fixture together.

## Set up

```bash
uv sync --locked
```

## Change the corpus

Import the local HTML checkout:

```bash
uv run python scripts/import_sgb.py ../sgb-minimal-html
uv run --group index python -m scripts.build_index
```

The importer discovers `html/volume-*/sgb-*.html` files in stable order.
It keeps headings, paragraphs, and sidebar text within `<main>`.
It skips each appendix chapter (`citation_title` `Anhang`). It removes footnote markers, separate endnotes, and technical metadata.
Chapter and volume titles share the index title field.
Authors remain in Markdown front matter. Missing authors do not exclude a chapter.

The importer owns `content/sgb-*.md`.
After a successful import, it removes generated chapters that no longer exist in the source checkout.
It preserves files outside that filename pattern.
It validates all source chapters before writing files or removing stale chapters.

Run the gate after the index build.
Commit the imported content, generated index, and generated reference fixture together.
Do not edit the generated JSON files by hand.

## Data Story coverage

The importer includes these seven publications from the [official catalogue](https://stadtgeschichtebasel.ch/data-stories):

| Publication | Author | Original |
| --- | --- | --- |
| Schulden in der Stadt | Benjamin Hitz | [Story](https://storymaps.arcgis.com/stories/1955ccada8d74ff6919e9e1397cb168a) |
| Verbriefte Märkte - Seidene Beziehungen | Yiğit Topkaya | [Story](https://storymaps.arcgis.com/stories/90a309d6d21342608d0ad3ee16fb3f30) |
| Bleibt die Kirche in der Stadt? | Benjamin Hitz, Jonas Aeby | [Story](https://storymaps.arcgis.com/stories/34ef391bd4fa419cb82d488906608154) |
| Von Basler Fumoirs & Schnupftabakdosen | Ariane Engler, Margherita De Fregias | [Story](https://storymaps.arcgis.com/stories/e2096bc80f714932b8eba10ee7e23b4b) |
| Konzil und Koran | Lucas Burkart | [Story](https://storymaps.arcgis.com/stories/0cac069fdac24f13a06377a1c7294a33) |
| Mit Bioarchäologie Geschichte schreiben | Margaux L. C. Depaermentier | [Story](https://storymaps.arcgis.com/stories/54d35e03bcdf4841b092d4c4906227e9) |
| Das Kontrollbüro und die Wundermaschine | Anna Cristina Wildisen-Münch, Nico Görlich, Moritz Mähr | [Story](https://storymaps.arcgis.com/stories/6be823309a7b4254aa27b5486703b68b) |

“Das jüdische Basel 1850 – 1914” is excluded at the repository owner's request.
The corpus includes visible narrative text, headings, cover summaries, sidecars, carousels, and guided-tour descriptions.
It excludes interactive applications, map data, images, audio, video, hidden nodes, and navigation.
Credits remain in front matter and do not enter the embeddings.
Full narrative coverage does not include text inside external embedded applications.

Refresh the seven stories explicitly:

```bash
uv run --locked python -m scripts.import_data_stories
uv run --locked --group index python -m scripts.build_index
```

The importer reads public metadata and published story data through the ArcGIS REST API.
It does not read draft resources, including when an item has unpublished edits.
It validates every story before writing generated `content/data-story-*.md` files.
A failed request or invalid story leaves the existing files unchanged.
It preserves chapter files and unrelated files.

The index build uses committed Markdown and does not crawl source websites.
The same source responses produce the same Markdown and stable passage identifiers.

Each story file records authorship, source URLs, modification and publication times, a source hash, credits, and original rights notices.
The repository owner authorised redistribution of all seven narrative texts on 2026-11-15.
This permission does not assign a Creative Commons licence to these stories.
Six ArcGIS items state no licence in their metadata.
The Kontrollbüro item requires author consent for redistribution and states that a Creative Commons licence is planned.
The permission above covers its inclusion here.

Chapter licences do not apply to the stories.

The index grew from 26.43 MB to 27.88 MB, an increase of 5.5 percent.
Compression with zlib at level 9 grew from 8.70 MB to 9.08 MB, an increase of 4.4 percent.
Host compression and network transfer times can differ.

Local JSON reading and validation took a median of 0.132 seconds before and 0.140 seconds after the change.
These measurements use five native Python runs on the development machine.
They do not measure browser startup or WebAssembly performance.
The query model and its download size stay unchanged.

## Gate

```bash
uv run ruff check . && uv run ruff format --check .
uv run ty check
uv run pytest
uv run marimo check app.py compare.py --select MW
```

Pytest includes doctests and requires 100% coverage of core logic.

## Export and local check

Use the complete export command:

```bash
uv run python -m scripts.export_site
python -m http.server --directory dist 8000
```

The command exports the notebook and sets de-CH and one SGB theme colour in the HTML.
It stops if the export fails or the expected HTML structure changes.
Keep this metadata step together with the export.
Open `http://localhost:8000/`. Do not open `dist/index.html` as a file.

## Browser tests

The browser tests run real WebAssembly inference in Chromium and Firefox.
They need `dist/`, Playwright browsers, and a network connection.
CI runs the gate and export checks. It does not run the browser suite.

```bash
uv run python -m scripts.export_site
uv run playwright install chromium firefox
uv run pytest -m browser --no-cov
```

The checks cover keyboard search, retry, publication links, status roles, accessible names, and focus styles.
They cover the mode control, query retention across mode changes, and keyboard access to the modes.
They block the model downloads. They verify that the lexical mode makes no model request and that the combined mode falls back to lexical results.
They also verify that the retry button recovers.
They verify story retrieval and the shared Data Stories volume title.
They also cover 320-pixel reflow, doubled root text size, and increased text spacing.
The text-size check approximates text-only zoom. It does not reproduce browser zoom exactly.
Manual screen-reader and browser-zoom checks remain useful before a release.
This targeted accessibility work is not a full WCAG conformance audit.
Loading uses live status text instead of animated spinners.

## Deployment

`.github/workflows/pages.yml` runs the gate and complete export for pull requests and pushes to `main`.
CI checks the exported document language directly.
Only `main` deploys after a successful build.
The deployment uses the `github-pages` environment.
The Pages source must be **GitHub Actions**.

## Branding and licences

`sgb.css` uses marimo's custom CSS support.
`head.html` adds the SGB favicon and the light colour scheme.
The export command sets the theme colour after marimo creates the HTML.
Asset URLs resolve below the GitHub Pages repository path.

The logo, favicon, and three Euclid Circular B font files come unchanged from
[sgb-theme](https://github.com/Stadt-Geschichte-Basel/sgb-theme/tree/8cd8beae6f7e157493cb2ceffba8fe3f187334e1/_extensions/sgb-theme).
Source revision: `8cd8beae6f7e157493cb2ceffba8fe3f187334e1`.
The source directory is `_extensions/sgb-theme/`.
The static font weights are Regular 400, Medium 500, and Semibold 600.
The upstream [content licence](https://github.com/Stadt-Geschichte-Basel/sgb-theme/blob/8cd8beae6f7e157493cb2ceffba8fe3f187334e1/LICENSE-CCBY.md) states CC BY 4.0.

The software uses AGPL-3.0-only. Refer to `LICENSE`.
Book chapter content is © Stadt.Geschichte.Basel / Christoph Merian Verlag,
under [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/).
Book chapters appear in the [publication catalog](https://emono.unibas.ch/stadtgeschichtebasel/catalog).
