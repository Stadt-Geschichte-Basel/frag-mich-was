# SPECS.md — Frag mich was

**Repository:** `Stadt-Geschichte-Basel/frag-mich-was`  
**Upstream:** [maehr/moritz-says](https://github.com/maehr/moritz-says)  
**Corpus:** [sgb-minimal-html](https://github.com/Stadt-Geschichte-Basel/sgb-minimal-html)  
**Specification language:** en-US  
**Product language:** de-CH

## 1. Goal

Build a semantic search interface for *Stadt.Geschichte.Basel*.

Users ask questions in natural language and discover relevant passages from the published book series.

**One chapter = one DOI = one search result.**

The application finds sources. It does not generate answers.

## 2. Principles

Follow the 80/20 rule. Reuse the existing `moritz-says` implementation wherever possible.

- Static GitHub Pages deployment.
- marimo and WebAssembly.
- Browser-side inference without a backend.
- Precomputed document embeddings.
- No database or external inference API.
- Minimal dependencies and code changes.
- No new tests or benchmarking.

Keep implementation simple. Prefer existing functionality over new abstractions.

## 3. Corpus

Source: `Stadt-Geschichte-Basel/sgb-minimal-html`.

Import all HTML files matching:

`html/volume-*/sgb-*.html`

The corpus currently contains 79 chapter editions across nine volumes. Discover files automatically rather than hardcoding the count.

Each HTML file represents one searchable chapter.

### Metadata

Extract:

| Field | HTML source |
|---|---|
| DOI | `citation_doi` |
| Chapter title | `citation_title` |
| Volume title | `citation_inbook_title` |
| Authors | `citation_author` |
| Main text | `<main>` |
| Source URL | `https://doi.org/<DOI>` |

Preserve headings, paragraphs, and historical terminology.

Exclude HTML markup, footnote markers, separate endnote lists, and technical metadata from embeddings.

Include introductions and appendices with chapter DOIs. Do not index volume DOIs as additional chapters.

## 4. Indexing

Keep the existing embedding model:

- **Model:** `intfloat/multilingual-e5-small`
- **Dimensions:** 384
- **Browser:** existing quantized ONNX model
- **Document prefix:** `passage: `
- **Query prefix:** `query: `
- **Chunk size:** existing 120–180 token configuration

Do not embed entire chapters as single vectors.

Add `scripts/import_sgb.py` to convert the HTML corpus into Markdown files under `content/`.

Reuse `scripts/build_index.py` to generate `public/embeddings.json`.

The importer should accept a local checkout:

```bash
uv run python scripts/import_sgb.py ../sgb-minimal-html
uv run --group index python -m scripts.build_index
```

Keep the existing index schema where possible. Store the chapter DOI in the source URL. The volume title may be included in the document title to avoid adding new metadata fields.

## 5. Search

Reuse the existing query embedding and cosine similarity implementation.

Change result ranking:

1. Rank all passages by similarity.
2. Group passages by chapter DOI.
3. Retain the highest-scoring passage per DOI.
4. Display the five highest-ranked distinct chapters.

Each result links to its original chapter through `https://doi.org/<DOI>`.

No reranking, keyword-search engine, or generated answers.

## 6. User interface

All user-facing text must use **Swiss Standard German (de-CH)**.

Use Swiss spelling (`ss` instead of `ß`) and appropriate Swiss conventions. Keep source quotations unchanged.

**Product name:** Frag mich was  
**Tagline:** Fragen stellen. Geschichte finden.

### Interface

- One search input.
- Button: **Suchen**
- Up to five results.
- Each result displays the chapter title, volume, relevant excerpt, and source link.
- Source link: **Originalkapitel öffnen**
- Link to the [publication catalog](https://emono.unibas.ch/stadtgeschichtebasel/catalog).
- Brief notice that search runs locally in the browser.

Example query:

*Welche Rolle spielte die Rheinfischerei für Basel?*

Keep the interface minimal and responsive.

## 7. Implementation

Work directly from the existing fork.

1. Replace `moritz-says` branding with **Frag mich was**.
2. Localize the interface to de-CH.
3. Add the HTML corpus importer.
4. Generate embeddings using the existing model.
5. Group search results by chapter DOI.
6. Deploy through the existing GitHub Pages workflow.

Do not redesign working components unnecessarily.

## 8. Out of scope

- New tests or test infrastructure.
- Embedding model comparisons.
- Vector databases.
- Backend services.
- LLM-generated responses.
- Chat interfaces.
- Advanced filters.
- Analytics.
- Automatic corpus synchronization.
- Premature performance optimization.

## 9. Definition of done

- All available chapter HTML files are indexed.
- German-language questions retrieve relevant passages.
- Each result represents a distinct chapter DOI.
- Results link to the original publications.
- The complete interface uses de-CH.
- The application runs on GitHub Pages without a backend.
- Search queries remain in the user's browser.

## 10. Licensing

Preserve the upstream **AGPL-3.0** software license.

The publication content is licensed under **CC BY-NC 4.0**, © Stadt.Geschichte.Basel / Christoph Merian Verlag.

Display appropriate attribution and license information. All indexed content is public.