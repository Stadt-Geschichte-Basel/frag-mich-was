"""Build ``public/embeddings.json`` and the test fixture from ``content/``.

Run from the repository root::

    uv run --group index python -m scripts.build_index
"""

import html
import importlib
import json
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from app import ModelInfo, load_index

ROOT = Path(__file__).resolve().parents[1]
CONTENT_DIR = ROOT / "content"
INDEX_FILE = ROOT / "public" / "embeddings.json"
FIXTURE_FILE = ROOT / "tests" / "fixtures" / "reference_vectors.json"

# Pinned models. The corpus is German and English, so the model is multilingual.
# E5 models need a prefix on each passage and on each query.
MODEL = ModelInfo(
    document_model="intfloat/multilingual-e5-small",
    document_revision="614241f622f53c4eeff9890bdc4f31cfecc418b3",
    query_model="Xenova/multilingual-e5-small",
    query_revision="761b726dd34fb83930e26aab4e9ac3899aa1fa78",
    dimensions=384,
    document_prefix="passage: ",
    query_prefix="query: ",
)

MIN_TOKENS = 120
MAX_TOKENS = 180
OVERLAP_TOKENS = 20
DECIMALS = 5

# Sentences with reference vectors. They detect a change of model, tokenizer, pooling, or
# normalization, and they are the comparison base for the browser model.
FIXTURE_SENTENCES = (
    "query: Wie hat die Verwaltung Computer eingesetzt, um Migration zu steuern?",
    "query: history of data protection in Switzerland",
    "query: How do I search many PDF files at once?",
    "passage: Die Bundesverwaltung führte in den 1960er-Jahren elektronische Datenverarbeitung ein.",
    "passage: We evaluate vision-language models that write alternative text for historical images.",
)

# A query in other words than the passage that it must find within the top three results.
REFERENCE_QUERY = "extract text from many PDF documents on the command line"
REFERENCE_EXPECTED_ID = "proghist-batches-pdf:0021"

SENTENCE_END = re.compile(r"(?<=[.!?…])\s+(?=[A-ZÄÖÜ\"„«“(\[])")


@dataclass(frozen=True)
class Document:
    """One source text with its metadata."""

    source: str
    title: str
    url: str | None
    body: str


def parse_document(name: str, raw: str) -> Document:
    """Split the front matter from the body. Use the file name if there is no title.

    >>> parse_document("my-note.md", "Text.").title
    'My note'
    >>> doc = parse_document("a.md", '---\\ntitle: "A: B"\\nurl: https://doi.org/10.1/x\\n---\\nText.')
    >>> (doc.title, doc.url, doc.body)
    ('A: B', 'https://doi.org/10.1/x', 'Text.')
    """
    meta: dict[str, str] = {}
    text = raw.replace("\r\n", "\n")
    body = text
    match = re.match(r"---\n(?:(.*?)\n)?---(?:\n|$)(.*)", text, flags=re.DOTALL)
    if match:
        body = match.group(2)
        for line in (match.group(1) or "").splitlines():
            key, colon, value = line.partition(":")
            if colon:
                value = value.strip()
                meta[key.strip()] = json.loads(value) if value.startswith('"') else value
    title = meta.get("title") or Path(name).stem.replace("-", " ").replace("_", " ").capitalize()
    return Document(source=name, title=title, url=meta.get("url") or None, body=body)


def clean_markdown(text: str) -> str:
    """Remove markup that is not part of the text: comments, images, link targets, tags, heading marks.

    >>> clean_markdown("## Title\\n<!-- note -->See [the *site*](https://example.org).![x](y.png)<br>")
    'Title\\nSee the site.'
    """
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"</?[a-zA-Z][^>]*>", "", text)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\$\^\{([^}]*)\}\$", r" \1", text)  # A footnote mark such as $^{12}$.
    text = html.unescape(text)
    text = re.sub(r"\\([\\`*_{}\[\]()#+.!|<>~$-])", r"\1", text)  # A Markdown escape such as \_.
    # An emphasis mark stands at a word boundary. Marks inside a word or a number stay.
    return re.sub(r"(?<![\w*_])(\*{1,3}|_{1,3})(?=\S)(.+?)(?<=\S)\1(?![\w*_])", r"\2", text)


def split_long(text: str, count_tokens: Callable[[str], int], max_tokens: int) -> list[str]:
    """Split a text at spaces into pieces of at most ``max_tokens``.

    >>> split_long("a b c d e", lambda text: len(text.split()), 2)
    ['a b', 'c d', 'e']
    """
    pieces: list[str] = []
    current: list[str] = []
    for word in text.split():
        if current and count_tokens(" ".join([*current, word])) > max_tokens:
            pieces.append(" ".join(current))
            current = []
        current.append(word)
    if current:
        pieces.append(" ".join(current))
    return pieces


def chunk_text(
    text: str,
    count_tokens: Callable[[str], int],
    min_tokens: int = MIN_TOKENS,
    max_tokens: int = MAX_TOKENS,
    overlap_tokens: int = OVERLAP_TOKENS,
) -> list[str]:
    """Split a text into passages of ``min_tokens`` to ``max_tokens`` at sentence boundaries.

    A paragraph end closes a passage that has ``min_tokens`` or more. A short last sentence
    of at most ``overlap_tokens`` starts the next passage again.

    >>> words = lambda text: len(text.split())
    >>> chunk_text("One two. Three four. Five six.", words, min_tokens=3, max_tokens=4, overlap_tokens=0)
    ['One two. Three four.', 'Five six.']
    """
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for paragraph in re.split(r"\n\s*\n", text):
        flat = " ".join(paragraph.split())
        for sentence in SENTENCE_END.split(flat) if flat else []:
            fits = count_tokens(sentence) <= max_tokens
            for unit in [sentence] if fits else split_long(sentence, count_tokens, max_tokens):
                tokens = count_tokens(unit)
                if current and size + tokens > max_tokens:
                    chunks.append(" ".join(current))
                    last = current[-1]
                    last_tokens = count_tokens(last)
                    keep = (
                        len(current) > 1
                        and last_tokens <= overlap_tokens
                        and last_tokens + tokens <= max_tokens
                    )
                    current, size = ([last], last_tokens) if keep else ([], 0)
                current.append(unit)
                size += tokens
        if size >= min_tokens:
            chunks.append(" ".join(current))
            current, size = [], 0
    if current:
        chunks.append(" ".join(current))
    return chunks


def build_chunks(
    documents: Iterable[Document], count_tokens: Callable[[str], int]
) -> list[dict[str, object]]:
    """Make the chunk records of all documents, without embeddings.

    >>> doc = Document(source="a.md", title="A", url=None, body="One two.")
    >>> build_chunks([doc], lambda text: len(text.split()))
    [{'id': 'a:0001', 'title': 'A', 'text': 'One two.', 'source': 'a.md', 'url': None}]
    """
    records: list[dict[str, object]] = []
    for document in documents:
        slug = Path(document.source).stem
        passages = chunk_text(clean_markdown(document.body), count_tokens)
        for number, text in enumerate(passages, start=1):
            records.append(
                {
                    "id": f"{slug}:{number:04d}",
                    "title": document.title,
                    "text": text,
                    "source": document.source,
                    "url": document.url,
                }
            )
    return records


def serialize_index(model: ModelInfo, chunks: Sequence[Mapping[str, object]]) -> str:
    """Write the index as deterministic JSON with one chunk on each line.

    >>> model = ModelInfo(
    ...     document_model="a", document_revision="1", query_model="b", query_revision="2", dimensions=1
    ... )
    >>> text = serialize_index(model, [{"id": "a:0001", "embedding": [1.0]}])
    >>> text.splitlines()[3]
    '{"id":"a:0001","embedding":[1.0]}'
    """
    head = json.dumps(model.model_dump(), ensure_ascii=False, separators=(",", ":"))
    lines = ",\n".join(
        json.dumps(chunk, ensure_ascii=False, separators=(",", ":")) for chunk in chunks
    )
    return f'{{"schema_version":1,\n"model":{head},\n"chunks":[\n{lines}\n]}}\n'


def main() -> None:  # pragma: no cover - needs the embedding model; tests read its committed output
    """Chunk and embed the content. Validate the index. Then write the index and the fixture."""
    # The index dependency group holds this package. The default environment does not.
    encoder = importlib.import_module("sentence_transformers").SentenceTransformer(
        MODEL.document_model, revision=MODEL.document_revision, device="cpu"
    )

    def count_tokens(text: str) -> int:
        return len(encoder.tokenizer.encode(text, add_special_tokens=False))

    def embed(texts: Sequence[str]) -> list[list[float]]:
        vectors = encoder.encode(list(texts), normalize_embeddings=True, batch_size=32)
        return [[round(float(value), DECIMALS) for value in vector] for vector in vectors]

    paths = sorted(p for p in CONTENT_DIR.iterdir() if p.suffix in {".md", ".txt"})
    documents = [parse_document(path.name, path.read_text(encoding="utf-8")) for path in paths]
    chunks = build_chunks(documents, count_tokens)

    # The model adds two special tokens. An unknown limit stops the build.
    limit = int(encoder.max_seq_length or 0) - 2
    too_long = [
        c["id"] for c in chunks if count_tokens(f"{MODEL.document_prefix}{c['text']}") > limit
    ]
    if too_long:
        raise SystemExit(f"Passages exceed the model input length: {too_long}")

    vectors = embed([f"{MODEL.document_prefix}{chunk['text']}" for chunk in chunks])
    for chunk, vector in zip(chunks, vectors, strict=True):
        chunk["embedding"] = vector
    text = serialize_index(MODEL, chunks)
    load_index(text)
    INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
    INDEX_FILE.write_text(text, encoding="utf-8")

    fixture = {
        "model": MODEL.model_dump(),
        "sentences": [
            {"text": sentence, "embedding": vector}
            for sentence, vector in zip(FIXTURE_SENTENCES, embed(FIXTURE_SENTENCES), strict=True)
        ],
        "reference": {
            "query": REFERENCE_QUERY,
            "expected_id": REFERENCE_EXPECTED_ID,
            "embedding": embed([MODEL.query_prefix + REFERENCE_QUERY])[0],
        },
    }
    FIXTURE_FILE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE_FILE.write_text(json.dumps(fixture, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{len(chunks)} passages from {len(documents)} documents -> {INDEX_FILE}")


if __name__ == "__main__":
    main()
