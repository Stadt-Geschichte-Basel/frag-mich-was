"""Check query prefixes and the fixture-only build without loading a model."""

import json
from pathlib import Path

import pytest

from app import load_index
from scripts import build_index
from scripts.comparison_queries import QUERY_EXAMPLES


class Encoder:
    def __init__(self) -> None:
        self.texts: list[str] = []

    def encode(
        self, texts: list[str], *, normalize_embeddings: bool, batch_size: int
    ) -> list[list[float]]:
        assert normalize_embeddings and batch_size == 32
        self.texts.extend(texts)
        return [[1.0, *([0.0] * (build_index.MODEL.dimensions - 1))] for _ in texts]


def test_fixture_builder_prefixes_every_query_and_preserves_reference_groups() -> None:
    encoder = Encoder()
    fixture = build_index.build_fixture(encoder)
    expected_texts = [
        *build_index.FIXTURE_SENTENCES,
        *(build_index.MODEL.query_prefix + query for query, _ in build_index.STORY_REFERENCES),
        *(build_index.MODEL.query_prefix + item.query for item in QUERY_EXAMPLES),
        build_index.MODEL.query_prefix + build_index.REFERENCE_QUERY,
    ]
    assert encoder.texts == expected_texts
    assert len(fixture["story_references"]) == 7
    assert len(fixture["comparison_references"]) == 36
    assert fixture["reference"]["expected_url"] == build_index.REFERENCE_EXPECTED_URL


def test_fixture_only_build_never_writes_the_passage_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    index_path, fixture_path = tmp_path / "index.json", tmp_path / "fixtures" / "vectors.json"
    original = build_index.serialize_index(build_index.MODEL, [])
    index_path.write_text(original, encoding="utf-8")
    monkeypatch.setattr(build_index, "INDEX_FILE", index_path)
    monkeypatch.setattr(build_index, "FIXTURE_FILE", fixture_path)
    monkeypatch.setattr(build_index, "load_encoder", Encoder)
    built: list[Encoder] = []
    monkeypatch.setattr(build_index, "write_index", built.append)

    build_index.main(["--fixtures-only"])
    assert not built
    assert index_path.read_text(encoding="utf-8") == original
    saved = json.loads(fixture_path.read_text(encoding="utf-8"))
    assert saved == build_index.build_fixture(Encoder())

    build_index.main([])
    assert len(built) == 1
    assert json.loads(fixture_path.read_text(encoding="utf-8")) == saved

    other = load_index(original).model.model_copy(update={"document_revision": "other"})
    index_path.write_text(build_index.serialize_index(other, []), encoding="utf-8")
    with pytest.raises(ValueError, match="another model"):
        build_index.main(["--fixtures-only"])
    assert json.loads(fixture_path.read_text(encoding="utf-8")) == saved
