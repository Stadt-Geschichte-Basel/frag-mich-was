"""Tests for authorised story imports and search metadata."""

import io
import json
from pathlib import Path
from typing import Any

import pytest

from app import Chunk, corpus_counts, is_safe_url, load_index, rank, render_results
from scripts import import_data_stories as importer
from scripts.build_index import build_chunks, parse_document


def item(**overrides: Any) -> str:
    return json.dumps(
        {
            "id": importer.STORIES[0].item_id,
            "title": "A story ",
            "access": "public",
            "modified": 123,
            "typeKeywords": ["smstatuspublished", "smpublisheddate:100"],
            "licenseInfo": "Original rights",
            "accessInformation": "Original author",
        }
        | overrides
    )


def graph() -> dict[str, Any]:
    return {
        "root": "root",
        "nodes": {
            "root": {
                "type": "story",
                "children": [
                    "cover",
                    "heading",
                    "sidecar",
                    "carousel",
                    "tour",
                    "hidden",
                    "credits",
                    "heading",
                    "script",
                    "nav",
                ],
            },
            "cover": {
                "type": "storycover",
                "data": {"title": "A story", "summary": "Subtitle", "byline": "A &amp; B"},
            },
            "heading": {"type": "text", "data": {"type": "h2", "text": "Heading"}},
            "sidecar": {"type": "immersive", "children": ["slide"]},
            "slide": {"type": "immersive-slide", "children": ["panel", "map"]},
            "panel": {"type": "immersive-narrative-panel", "children": ["text"]},
            "text": {
                "type": "text",
                "data": {"text": "<p>First <em>passage</em>.</p><p>Second.</p>"},
            },
            "map": {"type": "webmap", "data": {"text": "Ignore map configuration"}},
            "carousel": {"type": "carousel", "children": ["carousel-text"]},
            "carousel-text": {"type": "text", "data": {"text": "Carousel passage."}},
            "tour": {
                "type": "tour",
                "data": {
                    "places": [
                        {"title": "tour-title", "contents": ["tour-text"], "media": "map"},
                        {"contents": ["text"]},
                    ]
                },
            },
            "tour-title": {"type": "text", "data": {"text": "Tour place"}},
            "tour-text": {"type": "text", "data": {"text": "Tour passage."}},
            "hidden": {
                "type": "immersive",
                "config": {"isHidden": True},
                "children": ["missing-hidden-child"],
            },
            "credits": {"type": "credits", "children": ["credit-text", "attribution"]},
            "credit-text": {"type": "text", "data": {"text": "Rights notice"}},
            "attribution": {
                "type": "attribution",
                "data": {"content": "Credit", "attribution": "Author"},
            },
            "script": {"type": "code", "data": {"text": "Ignore code"}},
            "nav": {"type": "navigation", "children": ["missing-nav-child"]},
            "unreachable": {"type": "text", "data": {"text": "Ignore orphan"}},
        },
    }


def test_narrative_order_and_rights() -> None:
    data = importer.StoryData.model_validate(graph())
    body, authors, credits = importer.extract_story(data)
    assert (
        body
        == "A story\n\nSubtitle\n\n## Heading\n\nFirst passage.\n\nSecond.\n\nCarousel passage.\n\nTour place\n\nTour passage."
    )
    assert authors == "A & B"
    assert credits == "Rights notice\n\nCredit\n\nAuthor"
    assert (
        importer.narrative_html("<div>A<br>B</div><blockquote>C</blockquote><style>bad</style>")
        == "A\n\nB\n\nC"
    )
    raw = importer.convert(importer.STORIES[0], item(), json.dumps(graph()))
    assert raw == importer.convert(importer.STORIES[0], item(), json.dumps(graph()))
    assert 'license: "Original rights"' in raw
    assert 'copyright: "Original author"' in raw
    assert 'authors: "A & B"' in raw
    assert "Rights notice" in raw and importer.AUTHORISATION in raw
    assert "source_sha256:" in raw and 'published: "100"' in raw
    document = parse_document("story.md", raw)
    assert document.title == "A story — Data Stories"
    assert document.content_type == "data_story" and document.coverage == "full_text"
    records = build_chunks([document], lambda text: len(text.split()))
    assert records[0]["url"] == importer.STORIES[0].url
    assert records[0]["content_type"] == "data_story"
    records[0]["embedding"] = [1.0]
    chunk = Chunk.model_validate(records[0])
    html = render_results([(chunk, 1.0)])
    assert "Originalstory öffnen" in html and "— Data Stories" in html
    assert "Nur Zusammenfassung" not in html


@pytest.mark.parametrize(
    "overrides",
    [
        {"id": "wrong"},
        {"access": "private"},
        {"typeKeywords": ["smstatusdraft"]},
        {"typeKeywords": ["smstatuspublished"]},
    ],
)
def test_import_rejects_unpublished_or_wrong_items(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="approved public, published"):
        importer.convert(importer.STORIES[0], item(**overrides), json.dumps(graph()))


def test_import_uses_published_text_with_unpublished_edits_and_missing_rights() -> None:
    raw = importer.convert(
        importer.STORIES[0],
        item(
            licenseInfo=None,
            accessInformation=None,
            typeKeywords=["smstatusunpublishedchanges", "smpublisheddate:100"],
        ),
        json.dumps(graph()),
    )
    assert "No licence stated" in raw
    assert "See the original publication" in raw


def test_bad_story_graphs_fail() -> None:
    with pytest.raises(ValueError):
        importer.StoryData.model_validate_json("not json")
    with pytest.raises(ValueError, match="root is not a story"):
        importer.extract_story(importer.StoryData(root="a", nodes={"a": {"type": "text"}}))
    with pytest.raises(KeyError):
        importer.extract_story(
            importer.StoryData(root="a", nodes={"a": {"type": "story", "children": ["missing"]}})
        )
    with pytest.raises(ValueError, match="empty narrative"):
        importer.convert(
            importer.STORIES[0],
            item(),
            json.dumps({"root": "a", "nodes": {"a": {"type": "story"}}}),
        )


def test_fetch_bounds_the_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, int]] = []

    def open_response(url: str, timeout: int) -> io.BytesIO:
        calls.append((url, timeout))
        return io.BytesIO('"Gräber"'.encode())

    monkeypatch.setattr(importer, "urlopen", open_response)
    assert importer.fetch("https://example.org") == '"Gräber"'
    assert calls == [("https://example.org", 30)]


def test_import_validates_all_sources_before_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(importer, "ROOT", tmp_path)
    monkeypatch.setattr(importer, "STORIES", importer.STORIES[:1])

    def fetch(url: str) -> str:
        return json.dumps(graph()) if "/data?" in url else item()

    monkeypatch.setattr(importer, "fetch", fetch)
    importer.main()
    output = tmp_path / "content" / f"data-story-{importer.STORIES[0].slug}.md"
    before = output.read_text()
    unrelated = output.parent / "sgb-existing.md"
    unrelated.write_text("Keep chapter")
    importer.main()
    assert output.read_text() == before
    monkeypatch.setattr(
        importer, "STORIES", (*importer.STORIES, importer.Story("invalid", "wrong"))
    )
    with pytest.raises(ValueError):
        importer.main()
    assert output.read_text() == before
    assert unrelated.read_text() == "Keep chapter"
    assert not (output.parent / "data-story-invalid.md").exists()


def test_story_url_policy_and_metadata_validation() -> None:
    assert is_safe_url(importer.STORIES[0].url)
    for url in [
        "https://storymaps.arcgis.com/",
        "https://storymaps.arcgis.com/stories/short",
        "https://storymaps.arcgis.com/stories/" + "g" * 32,
        "https://storymaps.arcgis.com/stories/" + "a" * 32 + "/extra",
        importer.STORIES[0].url + "?redirect=elsewhere",
        importer.STORIES[0].url + "#x",
        importer.STORIES[0].url.replace("https://", "https://user@"),
        importer.STORIES[0].url.replace(".com/", ".com:443/"),
        importer.STORIES[0].url.replace(".com/", ".com.evil.test/"),
    ]:
        assert not is_safe_url(url), url
    record = {"id": "a", "title": "A", "text": "B", "source": "a.md", "embedding": [1.0]}
    for extra in [{"coverage": "partial"}, {"content_type": "unknown"}]:
        with pytest.raises(ValueError):
            Chunk.model_validate(record | extra)
    chunk = Chunk.model_validate(
        record
        | {"coverage": "summary", "content_type": "data_story", "url": importer.STORIES[0].url}
    )
    assert "Nur Zusammenfassung" in render_results([(chunk, 1.0)])
    legacy = load_index(
        json.dumps(
            {
                "schema_version": 1,
                "model": {
                    "document_model": "a",
                    "document_revision": "1",
                    "query_model": "b",
                    "query_revision": "2",
                    "dimensions": 1,
                },
                "chunks": [record],
            }
        )
    )
    assert legacy.chunks[0].content_type == "chapter"
    assert legacy.chunks[0].coverage == "full_text"


def test_stories_share_a_volume_but_remain_distinct_publications() -> None:
    chunks = [
        Chunk(
            id=str(n),
            title="Story — Data Stories",
            text="Text",
            source="a.md",
            content_type="data_story",
            url=story.url,
            embedding=[1.0],
        )
        for n, story in enumerate(importer.STORIES)
    ]
    duplicate = chunks[0].model_copy(update={"id": "duplicate"})
    results = rank([1.0], [duplicate, *chunks], top_k=10)
    chapter = Chunk(
        id="chapter", title="Chapter", text="Text", source="sgb-01.01.md", embedding=[1.0]
    )
    assert corpus_counts([*chunks, duplicate, chapter]) == (1, 7)
    assert len(results) == 7
    assert len({chunk.url for chunk, _ in results}) == 7


def test_cover_and_hidden_text_do_not_count_as_full_narrative() -> None:
    data = graph()
    data["nodes"]["root"]["children"] = ["cover", "hidden", "credits"]
    with pytest.raises(ValueError, match="empty narrative"):
        importer.convert(importer.STORIES[0], item(), json.dumps(data))
