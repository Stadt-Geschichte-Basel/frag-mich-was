# Contributing

## Report a problem

Open an issue. Give the query, the browser, and the result that you expected.

For a security problem, refer to [`SECURITY.md`](SECURITY.md). Do not open a public issue.

## Change the code

1. Fork the repository and make a topic branch.
2. Install the environment:

   ```bash
   uv sync --locked
   ```

3. Make the change. Add a test for it.
4. Run the gate:

   ```bash
   uv run ruff check . && uv run ruff format --check .
   uv run ty check
   uv run pytest
   uv run marimo check app.py --select MW
   ```

5. If the change touches `app.py`, run the browser tests. Refer to [`README.md`](README.md).
6. Open a pull request. Use a [Conventional Commit](https://www.conventionalcommits.org/en/v1.0.0/) as the title.

Keep one logical change in each pull request.

## Corpus

The maintainer selects the texts in `content/`.
Do not open a pull request that adds or changes a text.
Report an error in a text as an issue.

## Conduct

This project follows the [Code of Conduct](CODE_OF_CONDUCT.md).
