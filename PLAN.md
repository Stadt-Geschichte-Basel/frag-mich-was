# Hybrid search: 80/20 plan

This plan reduces the scope of `golden-sauteeing-key.md` for issue #20.
The first version adds word search beside the existing semantic search.
It uses one browser-built BM25 index and the existing result display.

## Required behaviour

- **Kombiniert** is the default mode. It combines lexical and semantic rankings.
- **Lexikalisch** finds words, names, and dates without the embedding model.
- **Semantisch** keeps the current search behaviour.
- A mode change keeps the submitted query.
- Results contain up to five distinct publications with their original links and excerpts.
- Search stays in the browser on the static GitHub Pages site.

## Implementation

### 1. Check the browser dependency

Test `bm25s` in a small exported marimo notebook with the committed index.
Use German stopwords without stemming.
Verify the same tokenization for passage titles, passage text, and queries.
Check installation and search in Chromium and Firefox.
Verify that indexing and search start no threads.
Measure index construction and one query on the development machine.
Use the source plan's limits: three seconds for construction and 200 milliseconds per query.
If compatibility or timing fails, report the measurements before changing the index format.

### 2. Add lexical ranking and combination

Pin the tested `bm25s` version in `pyproject.toml`.
Update `uv.lock`.
Build the lexical index once from the loaded passage titles and text.
Keep browser helpers at the top level of `app.py`.

Reuse the publication selection logic in `rank`.
Use `chunk.url or chunk.id` as the publication key.
Exclude lexical scores of zero or less.
Return no lexical matches for empty, stopword-only, or unknown queries.

Combine complete publication rankings with Reciprocal Rank Fusion (RRF).
Use one-based ranks and the fixed formula `sum(1 / (60 + rank))`.
Keep publications that appear in only one ranking.

Select the passage from the method with the better rank.
Select the semantic passage when both ranks match.
Break score ties by passage ID.
Apply the five-result limit after combination.

### 3. Connect the existing interface

Add an accessible three-option control outside the search form, above the results.
Keep the form independent from mode changes.
Check lexical mode before any model import or download.
Reuse `session` for the last successful query and its vector.
Reuse that vector when only the mode changes.

If the model fails in combined mode, show lexical results with a short notice.
Keep the existing retry button.
In semantic mode, keep the error message with a hint about lexical mode.

Reuse `render_results` and the current status roles.
Explain the modes in the existing de-CH help text.
Update search descriptions that become inaccurate, including metadata.
Update `README.md` and the runtime dependency list in `AGENTS.md`.

### 4. Verify the user-visible behaviour

Add focused tests for lexical matches, empty matches, publication selection, RRF, ties, and the result limit.
Keep doctests and 100 percent coverage for core logic.
Use the committed index for one name query and one date query.
Use existing reference vectors to check semantic and combined results.

Extend browser tests for mode changes, query retention, keyboard access, and 320-pixel reflow.
Block model downloads to verify lexical independence and combined fallback.
Verify successful recovery with the retry button.
Run the [repository gate](AGENTS.md#3-code) before committing.
Export the site with `uv run python -m scripts.export_site`.
Run `uv run pytest -m browser --no-cov` after implementation.

## Deferred scope

Stemming, relevance tuning, broader renaming, and a precomputed lexical index need evidence from this first version.
The first version keeps the existing corpus, index schema, generated fixtures, and index build process.
It adds no search framework, general cache, benchmark suite, or separate ranking display.
