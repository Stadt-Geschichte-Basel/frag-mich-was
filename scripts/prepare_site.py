"""Set the document language after the marimo WebAssembly export.

Run ``uv run python -m scripts.prepare_site`` after the export.
"""

import re
from pathlib import Path


def localize_html(raw: str) -> str:
    """Set de-CH without adding browser JavaScript.

    >>> localize_html('<html lang="en"><head></head></html>')
    '<html lang="de-CH"><head></head></html>'
    >>> localize_html('<html lang="de-CH"></html>')
    '<html lang="de-CH"></html>'
    >>> localize_html('<html></html>')
    Traceback (most recent call last):
    ValueError: Expected one marimo HTML language attribute.
    """
    result, count = re.subn(r'<html lang="(?:en|de-CH)">', '<html lang="de-CH">', raw)
    if count != 1:
        raise ValueError("Expected one marimo HTML language attribute.")
    return result


if __name__ == "__main__":
    path = Path(__file__).resolve().parents[1] / "dist" / "index.html"
    path.write_text(localize_html(path.read_text(encoding="utf-8")), encoding="utf-8")
