"""Import the seven authorised Data Stories from their public ArcGIS items.

>>> len(STORIES)
7
"""

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from pydantic import BaseModel, Field

from app import Chunk
from scripts.import_sgb import ChapterHTML

ROOT = Path(__file__).resolve().parents[1]
API = "https://www.arcgis.com/sharing/rest/content/items"
AUTHORISATION = "Full narrative redistribution authorised by the repository owner on 2026-11-15. Original rights notices remain applicable."


@dataclass(frozen=True)
class Story:
    """One approved publication.

    >>> Story("a", "b").url
    'https://storymaps.arcgis.com/stories/b'
    """

    slug: str
    item_id: str

    @property
    def url(self) -> str:
        """Return the original publication URL.

        >>> STORIES[0].url.startswith("https://storymaps.arcgis.com/stories/")
        True
        """
        return f"https://storymaps.arcgis.com/stories/{self.item_id}"


STORIES = (
    Story("schulden-in-der-stadt", "1955ccada8d74ff6919e9e1397cb168a"),
    Story("verbriefte-maerkte-seidene-beziehungen", "90a309d6d21342608d0ad3ee16fb3f30"),
    Story("bleibt-die-kirche-in-der-stadt", "34ef391bd4fa419cb82d488906608154"),
    Story("von-basler-fumoirs-und-schnupftabakdosen", "e2096bc80f714932b8eba10ee7e23b4b"),
    Story("konzil-und-koran", "0cac069fdac24f13a06377a1c7294a33"),
    Story("mit-bioarchaeologie-geschichte-schreiben", "54d35e03bcdf4841b092d4c4906227e9"),
    Story("das-kontrollbuero-und-die-wundermaschine", "6be823309a7b4254aa27b5486703b68b"),
)


class StoryItem(BaseModel):
    """Validate public publication metadata.

    >>> StoryItem(id="a", title="A", access="public", modified=1).licenseInfo is None
    True
    """

    id: str
    title: str = Field(min_length=1)
    access: str
    modified: int
    typeKeywords: list[str] = Field(default_factory=list)
    licenseInfo: str | None = None
    accessInformation: str | None = None


class StoryNode(BaseModel):
    """Validate one node in the published story.

    >>> StoryNode(type="text").children
    []
    """

    type: str
    data: dict[str, Any] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)
    children: list[str] = Field(default_factory=list)


class StoryData(BaseModel):
    """Validate the node graph at the import boundary.

    >>> StoryData(root="a", nodes={"a": {"type": "story"}}).root
    'a'
    """

    root: str
    nodes: dict[str, StoryNode]


def narrative_html(raw: str) -> str:
    """Keep narrative text and block boundaries from an HTML fragment.

    >>> narrative_html('<ul><li>A</li><li>B</li></ul><script>ignore()</script>')
    'A\\n\\nB'
    """
    parser = ChapterHTML()
    raw = re.sub(r"<(\/?)(?:li|div|blockquote)(?=[\s>])", r"<\1p", raw)
    parser.feed("<main>" + raw + "</main>")
    return parser.body()


def extract_story(data: StoryData) -> tuple[str, str, str]:
    """Read visible narrative nodes in publication order, including tour places.

    >>> extract_story(StoryData(root="a", nodes={"a": {"type": "story"}}))
    ('', '', '')
    """
    parts: list[str] = []
    authors = ""
    has_narrative = False
    credits: list[str] = []
    visited: set[str] = set()

    def visit(node_id: str, in_credits: bool = False) -> None:
        nonlocal authors, has_narrative
        if node_id in visited:
            return
        visited.add(node_id)
        node = data.nodes[node_id]
        if node.config.get("isHidden"):
            return
        if node.type == "storycover":
            authors = narrative_html(node.data.get("byline", ""))
            parts.extend(narrative_html(node.data.get(key, "")) for key in ("title", "summary"))
        elif node.type == "text":
            text = narrative_html(node.data.get("text", ""))
            kind = node.data.get("type", "")
            if re.fullmatch(r"h[1-6]", kind) and text:
                text = "#" * int(kind[1]) + " " + text
            (credits if in_credits else parts).append(text)
            if text.strip() and not in_credits:
                has_narrative = True
        elif node.type == "attribution":
            credits.extend(
                narrative_html(node.data.get(key, "")) for key in ("content", "attribution")
            )
        elif node.type in {
            "navigation",
            "embed",
            "code",
            "webmap",
            "expressmap",
            "tour-map",
            "image",
            "video",
            "audio",
            "button",
        }:
            return
        if node.type == "tour":
            for place in node.data.get("places", []):
                if place.get("title"):
                    visit(place["title"])
                for child in place.get("contents", []):
                    visit(child)
        for child in node.children:
            visit(child, in_credits or node.type == "credits")

    if data.nodes[data.root].type != "story":
        raise ValueError("The root is not a story.")
    visit(data.root)
    return (
        "\n\n".join(part for part in parts if part.strip()) if has_narrative else "",
        authors,
        "\n\n".join(part for part in credits if part.strip()),
    )


def convert(story: Story, metadata_raw: str, data_raw: str) -> str:
    """Validate a published story and produce reproducible Markdown.

    >>> callable(convert)
    True
    """
    item = StoryItem.model_validate_json(metadata_raw)
    if (
        item.id != story.item_id
        or item.access != "public"
        or not {"smstatuspublished", "smstatusunpublishedchanges"}.intersection(item.typeKeywords)
        or not any(key.startswith("smpublisheddate:") for key in item.typeKeywords)
    ):
        raise ValueError(f"{story.slug}: expected the approved public, published item")
    data = StoryData.model_validate_json(data_raw)
    body, authors, credits = extract_story(data)
    if not body.strip():
        raise ValueError(f"{story.slug}: empty narrative")
    title = item.title.strip() + " — Data Stories"
    # Validate the same URL and content metadata that the index accepts before any writes.
    Chunk(
        id=story.slug,
        title=title,
        text=body,
        source=story.slug,
        url=story.url,
        content_type="data_story",
        coverage="full_text",
        embedding=[1.0],
    )
    metadata = {
        "title": title,
        "url": story.url,
        "content_type": "data_story",
        "coverage": "full_text",
        "authors": authors,
        "license": item.licenseInfo or "No licence stated in source metadata.",
        "copyright": item.accessInformation or "See the original publication and its credits.",
        "credits": credits,
        "authorisation": AUTHORISATION,
        "catalogue_url": "https://stadtgeschichtebasel.ch/data-stories/" + story.slug,
        "metadata_url": f"{API}/{story.item_id}?f=json",
        "text_url": f"{API}/{story.item_id}/data?f=json",
        "source_modified": str(item.modified),
        "published": next(
            (
                key.split(":", 1)[1]
                for key in item.typeKeywords
                if key.startswith("smpublisheddate:")
            ),
            "",
        ),
        "source_sha256": hashlib.sha256(data_raw.encode("utf-8")).hexdigest(),
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


def fetch(url: str) -> str:
    """Read an ArcGIS JSON response with a bounded wait.

    >>> callable(fetch)
    True
    """
    with urlopen(url, timeout=30) as response:
        return response.read().decode("utf-8")


def main() -> None:
    """Fetch and validate every approved story before writing generated files.

    >>> callable(main)
    True
    """
    converted: list[tuple[str, str]] = []
    for story in STORIES:
        base = f"{API}/{story.item_id}"
        converted.append(
            (
                f"data-story-{story.slug}.md",
                convert(story, fetch(base + "?f=json"), fetch(base + "/data?f=json")),
            )
        )
    output = ROOT / "content"
    output.mkdir(exist_ok=True)
    for name, text in converted:
        (output / name).write_text(text, encoding="utf-8")
    print(f"Imported {len(converted)} Data Stories.")


if __name__ == "__main__":
    main()
