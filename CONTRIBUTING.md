# Contributing

## Report a problem

Open an issue. Give the query, the browser, and the result that you expected.

For a security problem, refer to [`SECURITY.md`](SECURITY.md). Do not open a public issue.

## Change the code

1. Make a topic branch. Fork the repository if you have no push access.
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

5. For browser-facing changes, run the browser tests. Refer to [`README.md`](README.md).
6. Open a pull request. Use a [Conventional Commit](https://www.conventionalcommits.org/en/v1.0.0/) as the title.

Keep one logical change in each pull request.

`main` requires pull requests, one independent approval, and a passing `build` check.
Resolve review conversations before merging.
New commits dismiss stale approvals.
Keep the branch current with `main`.
Use a squash merge to preserve linear history.
The protection also applies to administrators.
Force pushes and branch deletion are blocked.

## Corpus

The corpus comes from `Stadt-Geschichte-Basel/sgb-minimal-html`.
Use the import and index commands in [`README.md`](README.md).
Keep corpus changes and generated files together in the pull request.
Report source-text errors to the source repository.

## Conduct

This project follows the [Code of Conduct](CODE_OF_CONDUCT.md).
