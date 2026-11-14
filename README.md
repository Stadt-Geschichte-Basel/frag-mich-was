# Frag mich was

Frag mich was searches the chapters of Stadt.Geschichte.Basel by meaning.
The interface uses Swiss Standard German (de-CH).
The corpus contains German-language chapters, including introductions. It excludes appendices.
Source quotations keep their original spelling.
GitHub Pages hosts the static marimo WebAssembly application.
The application has no backend or inference API.

## Search

Enter a question or topic, then select **Suchen**.
For example: “Welche Bedeutung hatte der Rhein für Basel?”
Related wording can also find relevant passages.

Each result shows the chapter and volume title, an excerpt, and **Originalkapitel öffnen**.
The link opens the original publication through its DOI.
The page shows up to five distinct chapter DOIs.
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
7. Python ranks passages by cosine similarity and keeps each chapter's best passage.

The query stays in the browser. No inference service receives it.
All corpus text and embeddings are public. Do not add confidential or restricted text.

The index is about 36 MB before compression. Transfer size depends on host compression.
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

The checks cover keyboard search, retry, DOI links, status roles, accessible names, and focus styles.
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
Publication content is © Stadt.Geschichte.Basel / Christoph Merian Verlag,
under [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/).
Original publications appear in the [publication catalog](https://emono.unibas.ch/stadtgeschichtebasel/catalog).
