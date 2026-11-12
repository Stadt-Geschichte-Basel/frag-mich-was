"""Contract tests for the committed index and the reference vectors."""

import json
import math
from pathlib import Path

import pytest

from app import check_vector, load_index, rank
from scripts.build_index import (
    CONTENT_DIR,
    FIXTURE_FILE,
    FIXTURE_SENTENCES,
    INDEX_FILE,
    MODEL,
    REFERENCE_EXPECTED_URL,
    REFERENCE_QUERY,
)

INDEX = load_index(INDEX_FILE.read_text(encoding="utf-8"))
FIXTURE = json.loads(FIXTURE_FILE.read_text(encoding="utf-8"))


def test_index_and_fixture_use_the_pinned_models() -> None:
    assert INDEX.model == MODEL
    assert FIXTURE["model"] == MODEL.model_dump()
    assert MODEL.dimensions == 384


def test_index_covers_each_content_file() -> None:
    """A text that is not in the index shows that the index is out of date."""
    files = {path.name for path in Path(CONTENT_DIR).iterdir() if path.suffix in {".md", ".txt"}}
    assert {chunk.source for chunk in INDEX.chunks} == files


def test_fixture_vectors_are_valid() -> None:
    assert [item["text"] for item in FIXTURE["sentences"]] == list(FIXTURE_SENTENCES)
    for item in FIXTURE["sentences"]:
        check_vector(item["embedding"], MODEL.dimensions)


def test_reference_query_finds_the_expected_passage() -> None:
    """A query in other words finds the expected chapter within the top three."""
    reference = FIXTURE["reference"]
    assert (reference["query"], reference["expected_url"]) == (
        REFERENCE_QUERY,
        REFERENCE_EXPECTED_URL,
    )
    top = [chunk.url for chunk, _ in rank(reference["embedding"], INDEX.chunks, top_k=3)]
    assert REFERENCE_EXPECTED_URL in top


def test_python_model_reproduces_the_fixture() -> None:
    """Detect a change of model revision, tokenizer, pooling, or normalization.

    This test needs the ``index`` dependency group. Without the group, pytest skips it.
    """
    module = pytest.importorskip("sentence_transformers")
    encoder = module.SentenceTransformer(
        MODEL.document_model, revision=MODEL.document_revision, device="cpu"
    )
    vectors = encoder.encode(list(FIXTURE_SENTENCES), normalize_embeddings=True)
    for item, vector in zip(FIXTURE["sentences"], vectors, strict=True):
        assert math.sumprod(item["embedding"], [float(value) for value in vector]) > 0.999
