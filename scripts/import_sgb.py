"""Import chapter HTML from a local checkout.

>>> chapter = ChapterHTML()
>>> chapter.feed('<main><h2>Titel</h2><p>Ein <em>Wort</em>.<sup id="ref-fn1">1</sup></p></main>')
>>> chapter.body()
'## Titel\\n\\nEin Wort.'
"""

import argparse
import json
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VOID_ELEMENTS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)


class ChapterHTML(HTMLParser):
    """Collect citation metadata and chapter text.

    >>> ChapterHTML().metadata
    {}
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.metadata: dict[str, list[str]] = {}
        self.parts: list[str] = []
        self.active = False
        self.skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Read metadata and preserve block boundaries.

        >>> parser = ChapterHTML()
        >>> parser.feed('<meta name="citation_author" content="A">')
        >>> parser.metadata
        {'citation_author': ['A']}
        """
        values = dict(attrs)
        if tag == "meta":
            self.metadata.setdefault(values.get("name") or "", []).append(
                values.get("content") or ""
            )
        if tag == "main":
            self.active = True
        if self.active:
            if (
                self.skip
                or (values.get("id") or "").startswith("ref-fn")
                or values.get("role") == "doc-endnotes"
                or tag in {"script", "style"}
            ):
                if tag not in VOID_ELEMENTS:
                    self.skip += 1
            elif tag in {"p", "aside", "br"}:
                self.parts.append("\n\n")
            elif tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
                self.parts.append("\n\n" + "#" * int(tag[1]) + " ")

    def handle_endtag(self, tag: str) -> None:
        """Close a block or an excluded subtree.

        >>> parser = ChapterHTML()
        >>> parser.feed('<main><p>A</p><script>x</script><p>B</p></main>')
        >>> parser.body()
        'A\\n\\nB'
        """
        if tag in VOID_ELEMENTS:
            return
        if self.skip:
            self.skip -= 1
        elif self.active and tag in {"p", "aside", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self.parts.append("\n\n")
        if tag == "main":
            self.active = False

    def handle_data(self, data: str) -> None:
        """Keep only main text.

        >>> parser = ChapterHTML()
        >>> parser.feed('outside<main>inside</main>outside')
        >>> parser.body()
        'inside'
        """
        if self.active and not self.skip:
            self.parts.append(data)

    def body(self) -> str:
        """Normalize block whitespace.

        >>> ChapterHTML().body()
        ''
        """
        return "\n\n".join(
            " ".join(block.split()) for block in "".join(self.parts).split("\n\n") if block.strip()
        )


def convert(path: Path) -> str | None:
    """Convert one chapter with required citation metadata. Return None for an appendix.

    An appendix holds only bibliographies and registers. It is not searchable text.

    >>> from tempfile import TemporaryDirectory
    >>> with TemporaryDirectory() as directory:
    ...     path = Path(directory) / 'a.html'
    ...     _ = path.write_text('<main>Text</main>')
    ...     try:
    ...         convert(path)
    ...     except ValueError as error:
    ...         print(str(error).split(': ')[-1])
    missing citation_doi
    >>> html = ''.join(
    ...     f'<meta name="{n}" content="{v}">'
    ...     for n, v in [("citation_doi", "1"), ("citation_title", "Anhang"), ("citation_inbook_title", "B")]
    ... )
    >>> with TemporaryDirectory() as directory:
    ...     path = Path(directory) / 'a.html'
    ...     _ = path.write_text(html + '<main>Text</main>')
    ...     print(convert(path))
    None
    """
    parser = ChapterHTML()
    parser.feed(path.read_text(encoding="utf-8"))
    for name in ("citation_doi", "citation_title", "citation_inbook_title"):
        if not any(parser.metadata.get(name, [])):
            raise ValueError(f"{path}: missing {name}")
    if parser.metadata["citation_title"][0] == "Anhang":
        return None
    body = parser.body()
    if not body:
        raise ValueError(f"{path}: empty main text")
    metadata = {
        "title": parser.metadata["citation_title"][0]
        + " — "
        + parser.metadata["citation_inbook_title"][0],
        "url": "https://doi.org/" + parser.metadata["citation_doi"][0],
        "authors": "; ".join(parser.metadata.get("citation_author", [])),
        "license": "CC BY-NC 4.0",
        "copyright": "Stadt.Geschichte.Basel / Christoph Merian Verlag",
    }
    return (
        "---\n"
        + "\n".join(
            f"{key}: {json.dumps(value, ensure_ascii=False)}" for key, value in metadata.items()
        )
        + "\n---\n\n"
        + body
        + "\n"
    )


def main() -> None:
    """Import all discovered chapters.

    >>> callable(main)
    True
    """
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("checkout", type=Path)
    args = cli.parse_args()
    paths = sorted(args.checkout.glob("html/volume-*/sgb-*.html"))
    if not paths:
        raise ValueError("No chapter HTML files found.")
    converted = [(path.stem, convert(path)) for path in paths]
    chapters = [(stem, text) for stem, text in converted if text is not None]
    output = ROOT / "content"
    output.mkdir(exist_ok=True)
    for stem, text in chapters:
        (output / f"{stem}.md").write_text(text, encoding="utf-8")
    expected = {f"{stem}.md" for stem, _text in chapters}
    for stale in sorted(output.glob("sgb-*.md")):
        if stale.name not in expected:
            stale.unlink()
    print(f"Imported {len(chapters)} chapters.")


if __name__ == "__main__":
    main()
