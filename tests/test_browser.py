"""Browser tests for the exported site, with real WebAssembly inference.

These tests need the export in ``dist/``, the Playwright browsers, and network access::

    uv run python -m scripts.export_site
    uv run playwright install chromium firefox
    uv run pytest -m browser --no-cov
"""

import json
import math
import threading
from collections.abc import Iterator
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import BrowserContext, Page, Route, sync_playwright

from app import EMBEDDER_JS, QUERY_DTYPE, TRANSFORMERS_JS_URL, load_index

pytestmark = pytest.mark.browser

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
FIXTURE = json.loads((ROOT / "tests" / "fixtures" / "reference_vectors.json").read_text("utf-8"))
INDEX = load_index((ROOT / "public" / "embeddings.json").read_text("utf-8"))

# Hosts that supply the runtime, the packages, and the model files. None is an inference service.
ALLOWED_HOSTS = {"cdn.jsdelivr.net", "files.pythonhosted.org", "pypi.org", "wasm.marimo.app"}
ALLOWED_HOST_SUFFIXES = ("huggingface.co", ".hf.co")
LOAD_TIMEOUT = 180_000
MODEL_TIMEOUT = 420_000


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        """Keep the request lines out of the test output."""


@pytest.fixture(scope="module")
def site(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """Serve ``dist/`` below ``/frag-mich-was/``, as GitHub Pages does."""
    if not (DIST / "index.html").exists():
        pytest.fail("dist/index.html is missing. Run `uv run python -m scripts.export_site` first.")
    root = tmp_path_factory.mktemp("pages")
    (root / "frag-mich-was").symlink_to(DIST, target_is_directory=True)
    handler = partial(QuietHandler, directory=str(root))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://localhost:{server.server_port}/frag-mich-was/"
    server.shutdown()


@pytest.fixture(scope="module", params=["chromium", "firefox"])
def context(request: pytest.FixtureRequest) -> Iterator[BrowserContext]:
    """One browser context for each browser. The tests share its model cache."""
    with sync_playwright() as playwright:
        browser = getattr(playwright, request.param).launch()
        yield browser.new_context()
        browser.close()


def open_page(context: BrowserContext, hosts: set[str], errors: list[str]) -> Page:
    page = context.new_page()
    page.on("request", lambda request: hosts.add(urlsplit(request.url).hostname or ""))
    page.on("pageerror", lambda error: errors.append(str(error)))
    return page


def search(page: Page, query: str) -> None:
    field = page.get_by_role("textbox", name="Was möchtest du über Basels Geschichte wissen?")
    field.fill(query)
    field.press("Tab")
    button = page.get_by_role("button", name="Suchen")
    assert button.evaluate("el => el.getRootNode().activeElement === el")
    assert button.evaluate("el => getComputedStyle(el).outlineStyle") != "none"
    button.press("Enter")


def is_allowed(host: str) -> bool:
    local = host in {"", "localhost", "127.0.0.1"}
    return local or host in ALLOWED_HOSTS or host.endswith(ALLOWED_HOST_SUFFIXES)


def test_search_end_to_end(context: BrowserContext, site: str, tmp_path: Path) -> None:
    """Search by keyboard, preserve distinct chapters, and handle an empty query."""
    hosts: set[str] = set()
    errors: list[str] = []
    page = open_page(context, hosts, errors)
    page.goto(site)
    page.get_by_text(
        f"Du kannst alle {len({chunk.source[4:6] for chunk in INDEX.chunks})} Forschungsbände"
    ).wait_for(timeout=LOAD_TIMEOUT)
    page.reload()
    page.get_by_text(
        f"Du kannst alle {len({chunk.source[4:6] for chunk in INDEX.chunks})} Forschungsbände"
    ).wait_for(timeout=LOAD_TIMEOUT)

    assert page.locator("html").get_attribute("lang") == "de-CH"
    assert page.locator('meta[name="theme-color"]').count() == 1
    assert page.title() == "Frag mich was – Stadt.Geschichte.Basel"
    assert page.locator('meta[name="description"]').count() == 1
    assert page.locator('link[rel="canonical"]').count() == 1
    assert page.locator('meta[property^="og:"]').count() == 7
    assert page.locator('meta[name="theme-color"]').get_attribute("content") == "#3a1e3e"
    assert (
        page.get_by_role("heading", name="Frag mich was").evaluate(
            "element => getComputedStyle(element).fontWeight"
        )
        == "600"
    )
    assert page.get_by_role("status").filter(has_text="Du kannst").count() == 1
    logo = page.get_by_role("img", name="Stadt.Geschichte.Basel")
    assert logo.evaluate("image => image.complete && image.naturalWidth > 0")
    assert (
        page.get_by_role("heading", name="Frag mich was").evaluate(
            "element => getComputedStyle(element).color"
        )
        == "rgb(58, 30, 62)"
    )
    assert (
        page.locator(".sgb-brand").evaluate("element => getComputedStyle(element).backgroundColor")
        == "rgb(58, 30, 62)"
    )
    viewport_width = page.evaluate("window.innerWidth")
    for band in (".sgb-brand", ".sgb-footer"):
        box = page.locator(band).bounding_box()
        assert box is not None and abs(box["x"]) < 1 and abs(box["width"] - viewport_width) < 1
    assert page.locator(".sgb-brand a.sgb-portal").get_attribute("href") == (
        "https://stadtgeschichtebasel.ch/"
    )
    page.evaluate("document.fonts.ready")
    assert page.evaluate("document.fonts.check('16px \"Euclid Circular B\"')")
    for asset in [
        "public/sgb/favicon.png",
        *[
            f"public/sgb/assets/fonts/EuclidCircularB-{weight}-WebS.woff2"
            for weight in ("Regular", "Medium", "Semibold")
        ],
    ]:
        assert page.request.get(site + asset).ok
    assert (
        page.locator('link[rel="icon"][type="image/png"]').get_attribute("href")
        == "public/sgb/favicon.png"
    )

    search(page, "   ")
    page.get_by_text("Gib eine Frage oder ein Thema ein.").wait_for(timeout=LOAD_TIMEOUT)
    assert not any(host.endswith(ALLOWED_HOST_SUFFIXES) for host in hosts), "blank query"

    reference = FIXTURE["reference"]
    search(page, reference["query"])
    items = page.locator("ol li")
    items.first.wait_for(timeout=MODEL_TIMEOUT)
    texts = [" ".join(text.split()) for text in items.all_inner_texts()]
    assert 1 <= len(texts) <= 5
    assert page.get_by_role("status").filter(has_text="passende Kapitel gefunden").count() == 1
    assert items.get_by_role("heading", level=2).count() == len(texts)
    assert page.locator("ol.sgb-results").get_attribute("role") == "list"
    result_link = items.first.get_by_role("link")
    assert (result_link.get_attribute("aria-label") or "").startswith("Originalkapitel öffnen: ")
    result_box = result_link.bounding_box()
    assert result_box is not None and round(result_box["height"], 3) >= 24
    assert all("Ähnlichkeitswert" not in text for text in texts)
    assert page.get_by_text("Die Suche zeigt passende Textstellen,", exact=False).is_visible()
    expected = next(chunk for chunk in INDEX.chunks if chunk.url == reference["expected_url"])
    assert expected.url in items.locator("a").evaluate_all(
        "links => links.slice(0, 3).map(link => link.href)"
    )

    links = items.locator("a").evaluate_all("links => links.map(link => link.href)")
    assert len(set(links)) == len(texts)
    assert all(link.startswith("https://doi.org/") for link in links)
    page.mouse.move(0, 0)
    assert (
        page.get_by_role("button", name="Suchen").evaluate(
            "element => getComputedStyle(element).backgroundColor"
        )
        == "rgb(58, 30, 62)"
    )
    page.screenshot(path=str(tmp_path / "desktop.png"), full_page=True)
    items.first.screenshot(path=str(tmp_path / "desktop-result.png"))
    page.set_viewport_size({"width": 390, "height": 844})
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    # Firefox reports fractional geometry slightly below integer CSS pixel sizes.
    button_box = page.get_by_role("button", name="Suchen").bounding_box()
    assert button_box is not None and round(button_box["height"], 3) >= 44
    logo.scroll_into_view_if_needed()
    page.screenshot(path=str(tmp_path / "mobile.png"), full_page=True)
    items.first.screenshot(path=str(tmp_path / "mobile-result.png"))
    about = page.locator("details").filter(has=page.locator("summary", has_text="Über die Suche"))
    assert about.get_attribute("open") is None
    summary = about.locator("summary")
    summary.focus()
    summary.press("Enter")
    assert summary.evaluate("el => getComputedStyle(el).outlineWidth") == "3px"
    assert about.get_by_text("Deine Frage wird lokal", exact=False).is_visible()
    assert about.get_by_role("link", name="Publikationskatalog").is_visible()
    assert about.get_by_role("link", name="CC BY-NC 4.0").is_visible()
    page.set_viewport_size({"width": 320, "height": 844})
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.set_viewport_size({"width": 1280, "height": 900})
    page.evaluate(
        "document.documentElement.style.fontSize = (parseFloat(getComputedStyle(document.documentElement).fontSize) * 2) + 'px'"
    )
    page.add_style_tag(
        content="* { line-height: 1.5 !important; letter-spacing: .12em !important; word-spacing: .16em !important; } p { margin-bottom: 2em !important; }"
    )
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    summary.scroll_into_view_if_needed()
    page.screenshot(path=str(tmp_path / "large-text.png"), full_page=True)
    print(f"Interface previews: {tmp_path}")
    assert not errors
    assert all(is_allowed(host) for host in hosts), sorted(hosts)
    page.close()


def test_browser_vectors_match_python(context: BrowserContext, site: str) -> None:
    """The browser model and the Python model give the same vectors."""
    page = context.new_page()
    page.goto(site)
    model = FIXTURE["model"]
    sentences = [item["text"] for item in FIXTURE["sentences"]]
    vectors = page.evaluate(
        f"""async ([url, modelId, revision, dtype, texts]) => {{
            const embed = await ({EMBEDDER_JS})(url, modelId, revision, dtype);
            const vectors = [];
            for (const text of texts) vectors.push(await embed(text));
            return vectors;
        }}""",
        [
            TRANSFORMERS_JS_URL,
            model["query_model"],
            model["query_revision"],
            QUERY_DTYPE,
            sentences,
        ],
    )
    for item, vector in zip(FIXTURE["sentences"], vectors, strict=True):
        assert len(vector) == len(item["embedding"]) == model["dimensions"] == 384
        assert math.hypot(*vector) == pytest.approx(1.0, abs=0.01)
        assert math.hypot(*item["embedding"]) == pytest.approx(1.0, abs=0.01)
        assert math.sumprod(vector, item["embedding"]) >= 0.98, item["text"]
    page.close()


@pytest.mark.parametrize(
    ("status", "body", "message"),
    [
        (404, "not found", "Die Suche ist nicht verfügbar."),
        (200, "{not json", "Die Suche ist nicht verfügbar."),
        (200, json.dumps({"schema_version": 2}), "Die Suche ist nicht verfügbar."),
        (
            200,
            json.dumps({"schema_version": 1, "model": FIXTURE["model"], "chunks": []}),
            "Zurzeit sind keine Kapitel verfügbar. Versuche es später nochmals.",
        ),
    ],
)
def test_bad_index_shows_message(
    context: BrowserContext, site: str, status: int, body: str, message: str
) -> None:
    """A missing, invalid, or empty index gives a message and no search field."""
    errors: list[str] = []
    page = open_page(context, set(), errors)
    page.route("**/public/embeddings.json", lambda route: route.fulfill(status=status, body=body))
    page.goto(site)
    page.get_by_text(message).wait_for(timeout=LOAD_TIMEOUT)
    assert page.get_by_role("textbox").count() == 0
    role = "status" if "Zurzeit" in message else "alert"
    assert page.get_by_role(role).filter(has_text=message).count() == 1
    assert not errors
    page.close()


def test_model_failure_shows_retry(context: BrowserContext, site: str) -> None:
    """A failed model download gives an error with a retry that works."""
    assert context.browser is not None
    fresh = context.browser.new_context()  # An empty cache, so that the model must download.
    errors: list[str] = []
    page = open_page(fresh, set(), errors)

    def block(route: Route) -> None:
        route.abort()

    page.route("https://huggingface.co/**", block)
    page.goto(site)
    page.get_by_text(
        f"Du kannst alle {len({chunk.source[4:6] for chunk in INDEX.chunks})} Forschungsbände"
    ).wait_for(timeout=LOAD_TIMEOUT)
    search(page, FIXTURE["reference"]["query"])
    page.get_by_text("Die Suche ist fehlgeschlagen.").wait_for(timeout=MODEL_TIMEOUT)
    assert page.locator("ol li").count() == 0

    page.unroute("https://huggingface.co/**", block)
    assert page.get_by_role("alert").filter(has_text="Die Suche ist fehlgeschlagen.").count() == 1
    page.get_by_role("button", name="Erneut versuchen").press("Enter")
    page.locator("ol li").first.wait_for(timeout=MODEL_TIMEOUT)
    assert not errors
    fresh.close()
