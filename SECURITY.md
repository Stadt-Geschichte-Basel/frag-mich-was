# Security policy

## Report a vulnerability

Do not open a public issue for a vulnerability.

Use the private report form: <https://github.com/maehr/moritz-says/security/advisories/new>.
Describe the problem, the steps to reproduce it, and the effect.

## Supported version

Only the latest commit on `main` gets security fixes.

## Scope

The site is static. It has no server, no account, and no stored visitor data.
The query stays in the browser of the visitor.

These parts are in scope: the page code in `app.py`, the index build in `scripts/`, and the workflow in `.github/workflows/`.
