# Frag mich was

Frag mich was searches the research chapters and seven Data Stories of Stadt.Geschichte.Basel by meaning.
The interface uses Swiss Standard German (de-CH).
The corpus contains German-language chapters, including introductions. It excludes appendices.
Source quotations keep their original spelling.
GitHub Pages hosts the static marimo WebAssembly application.
The application has no backend or inference API.

## Search

Enter a question or topic, then select **Suchen**.
For example: “Welche Bedeutung hatte der Rhein für Basel?”
Related wording can also find relevant passages.

Each result shows the publication title, its volume title, an excerpt, and a link to the original.
Chapter links show **Originalkapitel öffnen** and use the DOI.
Story links show **Originalstory öffnen** and open ArcGIS StoryMaps.
All stories use **Data Stories** as their shared volume title.
The page shows up to five distinct publications in one ranking.
A **Nur Zusammenfassung** label marks records that contain only a description.
The seven current story records contain full narrative text.
Results are excerpts ranked by similarity, not generated or verified answers.
The interface does not show numeric similarity scores.

**Über die Suche** contains source, publisher, search limitation, privacy, licence, catalog, and source-code information.
The disclosure sits below the search results.

## How it works

1. The importer converts chapter HTML into Markdown files under `content/`.
2. The index builder splits each text into passages of 120 to 180 model tokens.
3. The builder calculates normalized embeddings with the pinned multilingual model.
4. The builder writes passages and embeddings to `public/embeddings.json`.
5. The browser loads and validates the index.
6. A quantized ONNX model calculates the query embedding in the browser.
7. Python ranks passages by cosine similarity and keeps each publication's best passage.

The query stays in the browser. No inference service receives it.
All corpus text and embeddings are public. Do not add confidential or restricted text.

The index size and local parsing measurements appear under **Data Story coverage** below.
Transfer size depends on host compression.
The first search also downloads a model of about 120 MB.
The first visit needs a network connection.
The application does not promise complete offline operation.

Runtime and model downloads use `cdn.jsdelivr.net`, `files.pythonhosted.org`, `pypi.org`, `wasm.marimo.app`, and Hugging Face file hosts.
Branding assets load from this site's `public/sgb/` directory.

## Models

| Use | Model | Where to pin |
| --- | --- | --- |
| Passages, at build time | `intfloat/multilingual-e5-small` | `MODEL` in `scripts/build_index.py` |
| Queries, in the browser | `Xenova/multilingual-e5-small`, `q8` | `MODEL` in `scripts/build_index.py`, `QUERY_DTYPE` in `app.py` |
| Browser runtime | Transformers.js | `TRANSFORMERS_JS_URL` in `app.py` |

The index records immutable model revisions, 384 dimensions, normalization, and the E5 prefixes.
The page reads the query model from the index.
The native embedding dependencies stay in the `index` dependency group.

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
uv run marimo check app.py --select MW
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
