"""Export the site with its required metadata.

Run ``uv run python -m scripts.export_site`` from the repository root.
"""

import re
import subprocess
import sys
from pathlib import Path

from scripts.comparison_report import build_report

ROOT = Path(__file__).resolve().parents[1]


def prepare_html(raw: str) -> str:
    """Set de-CH and one SGB theme colour. Drop marimo's default description.

    >>> raw = '<html lang="en"><head><meta name="theme-color" content="#000000" /></head></html>'
    >>> prepare_html(raw)
    '<html lang="de-CH"><head><meta name="theme-color" content="#3a1e3e"></head></html>'
    >>> prepare_html('<html lang="en"><head><meta name="description" content="a marimo app" /></head></html>')
    '<html lang="de-CH"><head><meta name="theme-color" content="#3a1e3e"></head></html>'
    >>> prepare_html(prepare_html(raw)) == prepare_html(raw)
    True
    >>> prepare_html('<html></html>')
    Traceback (most recent call last):
    ValueError: Expected one marimo HTML language attribute.
    >>> prepare_html('<html lang="en"></html>')
    Traceback (most recent call last):
    ValueError: Expected one HTML head closing tag.
    """
    result, count = re.subn(r'<html lang="(?:en|de-CH)">', '<html lang="de-CH">', raw)
    if count != 1:
        raise ValueError("Expected one marimo HTML language attribute.")
    if result.count("</head>") != 1:
        raise ValueError("Expected one HTML head closing tag.")
    result = re.sub(r'<meta name="theme-color" content="[^"]*"\s*/?>', "", result)
    result = re.sub(r'<meta name="description" content="a marimo app"\s*/?>', "", result)
    return result.replace("</head>", '<meta name="theme-color" content="#3a1e3e"></head>')


def main() -> None:
    """Export both notebooks and their validated comparison report.

    >>> callable(main)
    True
    """
    for notebook, output, filename in (
        ("app.py", "dist", "index.html"),
        ("compare.py", "dist/vergleich.html", "vergleich.html"),
    ):
        subprocess.run(
            [
                sys.executable,
                "-m",
                "marimo",
                "export",
                "html-wasm",
                notebook,
                "-o",
                output,
                "--mode",
                "run",
            ],
            cwd=ROOT,
            check=True,
        )
        path = ROOT / "dist" / filename
        path.write_text(prepare_html(path.read_text(encoding="utf-8")), encoding="utf-8")
    if any((ROOT / "dist" / "public" / "wheels").glob("*.whl")):
        raise ValueError("Local Python wheels must not enter the site export.")
    report = build_report()
    report_path = ROOT / "dist" / "public" / "comparison.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report.model_dump_json() + "\n", encoding="utf-8")
    # Re-read the deployed artifact through the same validation boundary as the browser.
    type(report).model_validate_json(report_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
