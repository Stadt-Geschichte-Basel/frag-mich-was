"""Browser tests for the exported site, with real WebAssembly inference.

These tests need the export in ``dist/``, the Playwright browsers, and network access::

    uv run python -m scripts.export_site
    uv run playwright install chromium firefox
    uv run pytest -m browser --no-cov
"""

import importlib.metadata
import json
import math
import sys
import threading
import time
import tomllib
from collections.abc import Iterator
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import BrowserContext, Page, Route, expect, sync_playwright

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
    field = page.get_by_role("textbox", name="Wonach suchst du in Basels Geschichte?")
    field.fill(query)
    field.press("Tab")
    button = page.get_by_role("button", name="Suchen")
    assert button.evaluate("el => el.getRootNode().activeElement === el")
    assert button.evaluate("el => getComputedStyle(el).outlineStyle") != "none"
    button.press("Enter")


def choose_mode(page: Page, label: str) -> None:
    """Select a search mode and wait until the control shows it."""
    mode = page.get_by_role("combobox", name="Suchmodus")
    mode.select_option(label=label)
    expect(mode).to_have_value(label)


def is_model_request(url: str) -> bool:
    """A request for the model runtime or the model files."""
    host = urlsplit(url).hostname or ""
    return host.endswith(ALLOWED_HOST_SUFFIXES) or "@huggingface/transformers" in url


def result_links(page: Page) -> list[str]:
    return page.locator("ol.sgb-results a").evaluate_all("links => links.map(link => link.href)")


def wait_for_links(page: Page, expected: list[str], timeout: float = 15.0) -> None:
    """Wait until the results show the expected links. Marimo replaces the output a little later."""
    deadline = time.monotonic() + timeout
    while (links := result_links(page)) != expected:
        assert time.monotonic() < deadline, f"{links} is not {expected}"
        page.wait_for_timeout(200)


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
        f"{len({chunk.source[4:6] for chunk in INDEX.chunks if chunk.content_type == 'chapter'})} Forschungsbände"
    ).wait_for(timeout=LOAD_TIMEOUT)
    page.reload()
    page.get_by_text(
        f"{len({chunk.source[4:6] for chunk in INDEX.chunks if chunk.content_type == 'chapter'})} Forschungsbände"
    ).wait_for(timeout=LOAD_TIMEOUT)

    assert page.locator("html").get_attribute("lang") == "de-CH"
    assert page.locator('meta[name="theme-color"]').count() == 1
    assert page.title() == "Frag mich was – Semantische Suche | Stadt.Geschichte.Basel"
    assert page.locator('meta[name="description"]').count() == 1
    assert "Lexikalische und semantische Suche" in (
        page.locator('meta[name="description"]').get_attribute("content") or ""
    )
    assert page.locator('meta[property="og:title"]').get_attribute("content") == page.title()
    assert page.locator('meta[property="og:description"]').get_attribute("content") == page.locator(
        'meta[name="description"]'
    ).get_attribute("content")
    assert (
        page.get_by_role("textbox", name="Wonach suchst du in Basels Geschichte?").get_attribute(
            "placeholder"
        )
        == "Rhein und Handel in Basel"
    )
    assert page.get_by_text(
        "Lexikalische und semantische Suche für Basels Geschichte."
    ).is_visible()
    mode = page.get_by_role("combobox", name="Suchmodus")
    assert mode.is_visible()
    assert mode.locator("option").all_inner_texts() == ["Kombiniert", "Lexikalisch", "Semantisch"]
    expect(mode).to_have_value("Semantisch")
    assert page.locator('link[rel="canonical"]').count() == 1
    assert page.locator('meta[property^="og:"]').count() == 7
    assert page.locator('meta[name="theme-color"]').get_attribute("content") == "#3a1e3e"
    assert (
        page.get_by_role("heading", name="Frag mich was").evaluate(
            "element => getComputedStyle(element).fontWeight"
        )
        == "600"
    )
    assert page.get_by_role("status").filter(has_text="Forschungsbände").count() == 1
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

    assert page.get_by_text("Gib ein Thema oder eine Frage ein.", exact=False).count() == 0
    search(page, "   ")
    page.get_by_text("Gib ein Thema oder eine Frage ein.").wait_for(timeout=LOAD_TIMEOUT)
    assert not any(host.endswith(ALLOWED_HOST_SUFFIXES) for host in hosts), "blank query"

    reference = FIXTURE["reference"]
    search(page, reference["query"])
    items = page.locator("ol li")
    items.first.wait_for(timeout=MODEL_TIMEOUT)
    texts = [" ".join(text.split()) for text in items.all_inner_texts()]
    assert 1 <= len(texts) <= 5
    assert (
        page.get_by_role("status").filter(has_text="passende Publikationen gefunden").count() == 1
    )
    assert items.get_by_role("heading", level=2).count() == len(texts)
    assert page.locator("ol.sgb-results").get_attribute("role") == "list"
    result_link = items.first.get_by_role("link")
    assert (result_link.get_attribute("aria-label") or "").startswith("Originalkapitel öffnen: ")
    result_box = result_link.bounding_box()
    assert result_box is not None and round(result_box["height"], 3) >= 24
    assert all("Ähnlichkeitswert" not in text for text in texts)
    assert page.get_by_text("Die Ergebnisse sind Textauszüge", exact=False).is_visible()
    expected = next(chunk for chunk in INDEX.chunks if chunk.url == reference["expected_url"])
    assert expected.url in items.locator("a").evaluate_all(
        "links => links.slice(0, 3).map(link => link.href)"
    )

    links = items.locator("a").evaluate_all("links => links.map(link => link.href)")
    assert len(set(links)) == len(texts)
    assert all(
        link.startswith(("https://doi.org/", "https://storymaps.arcgis.com/stories/"))
        for link in links
    )
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
    assert about.get_by_text("Deine Eingabe wird lokal", exact=False).is_visible()
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


def test_layout_reflows_at_320px_with_large_text(context: BrowserContext, site: str) -> None:
    """With doubled text and extra spacing, no element may extend past the viewport.

    marimo scrolls an inner container, so the document width alone shows nothing.
    """
    page = context.new_page()
    page.set_viewport_size({"width": 320, "height": 700})
    page.goto(site)
    page.get_by_role("status").filter(has_text="Forschungsbände").wait_for(timeout=LOAD_TIMEOUT)
    submit_box = page.get_by_role("button", name="Suchen").bounding_box()
    assert submit_box is not None and submit_box["y"] + submit_box["height"] <= 700
    page.add_style_tag(
        content="html{font-size:200%!important}"
        "*{line-height:1.5!important;letter-spacing:.12em!important;word-spacing:.16em!important}"
        "p{margin-bottom:2em!important}"
    )
    page.locator("details").wait_for(timeout=LOAD_TIMEOUT)
    page.evaluate("document.querySelector('details').open = true")
    clipped_script = """() => [...document.querySelectorAll('body *')]
        .filter(e => getComputedStyle(e).position !== 'fixed'
            && e.getBoundingClientRect().width > 0
            && e.getBoundingClientRect().right > innerWidth + 1)
        .map(e => e.tagName + ' ' + (e.textContent || '').slice(0, 30))"""
    assert page.get_by_role("combobox", name="Suchmodus").is_visible()
    assert page.evaluate(clipped_script) == []
    # The lexical mode needs no model, so the results show at once.
    choose_mode(page, "Lexikalisch")
    search(page, "Merian")
    page.locator("ol.sgb-results li").first.wait_for(timeout=LOAD_TIMEOUT)
    assert page.evaluate(clipped_script) == []
    page.close()


def test_mode_control_works_with_the_keyboard(context: BrowserContext, site: str) -> None:
    """Tab reaches the mode list. A key selects the mode. The lexical search needs no model."""
    errors: list[str] = []
    page = open_page(context, set(), errors)
    page.goto(site)
    page.get_by_role("status").filter(has_text="Forschungsbände").wait_for(timeout=LOAD_TIMEOUT)
    mode = page.get_by_role("combobox", name="Suchmodus")
    box = mode.bounding_box()
    assert box is not None and round(box["height"], 3) >= 44
    page.get_by_role("button", name="Suchen").focus()
    page.keyboard.press("Tab")
    assert mode.evaluate("element => element.getRootNode().activeElement === element")
    assert mode.evaluate("element => getComputedStyle(element).outlineWidth") == "3px"
    page.keyboard.press("L")  # The list selects the option that starts with the typed letter.
    expect(mode).to_have_value("Lexikalisch")
    search(page, "1501")
    page.locator("ol.sgb-results li").first.wait_for(timeout=LOAD_TIMEOUT)
    texts = [" ".join(text.split()) for text in page.locator("ol.sgb-results li").all_inner_texts()]
    assert 1 <= len(texts) <= 5
    assert all("1501" in text for text in texts)
    assert len(set(result_links(page))) == len(texts)
    assert not errors
    page.close()


@pytest.mark.parametrize(
    ("width", "height", "large_text"), [(390, 900, False), (1280, 900, False), (320, 700, True)]
)
def test_footer_ends_the_page(
    context: BrowserContext, site: str, width: int, height: int, large_text: bool
) -> None:
    """No white space may follow the footer inside marimo's scroll container."""
    page = context.new_page()
    page.set_viewport_size({"width": width, "height": height})
    page.goto(site)
    page.get_by_role("status").filter(has_text="Forschungsbände").wait_for(timeout=LOAD_TIMEOUT)
    page.locator(".sgb-footer").wait_for(timeout=LOAD_TIMEOUT)
    if large_text:
        page.add_style_tag(
            content="html{font-size:200%!important}"
            "*{line-height:1.5!important;letter-spacing:.12em!important;word-spacing:.16em!important}"
        )
    gap = page.evaluate(
        """() => {
        const footer = document.querySelector('.sgb-footer');
        let node = footer.parentElement;
        while (node && node.scrollHeight <= node.clientHeight + 1) node = node.parentElement;
        const scroller = node || document.scrollingElement;
        scroller.scrollTop = scroller.scrollHeight;
        const bottom = scroller === document.scrollingElement
            ? innerHeight : scroller.getBoundingClientRect().bottom;
        return bottom - footer.getBoundingClientRect().bottom;
    }"""
    )
    assert -1 <= gap <= 1, f"{gap}px below the footer"
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
            "Zurzeit sind keine Publikationen verfügbar. Versuche es später nochmals.",
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
        f"{len({chunk.source[4:6] for chunk in INDEX.chunks if chunk.content_type == 'chapter'})} Forschungsbände"
    ).wait_for(timeout=LOAD_TIMEOUT)
    # The default mode is Semantisch. A failed model download is an error there.
    expect(page.get_by_role("combobox", name="Suchmodus")).to_have_value("Semantisch")
    search(page, FIXTURE["reference"]["query"])
    page.get_by_text("Die Suche ist fehlgeschlagen.").wait_for(timeout=MODEL_TIMEOUT)
    assert page.get_by_text("Die lexikalische Suche braucht das Sprachmodell nicht.").is_visible()
    assert page.locator("ol li").count() == 0

    page.unroute("https://huggingface.co/**", block)
    assert page.get_by_role("alert").filter(has_text="Die Suche ist fehlgeschlagen.").count() == 1
    page.get_by_role("button", name="Erneut versuchen").press("Enter")
    page.locator("ol li").first.wait_for(timeout=MODEL_TIMEOUT)
    assert not errors
    fresh.close()


def test_story_search_end_to_end(context: BrowserContext, site: str, tmp_path: Path) -> None:
    """Retrieve a story with real inference and preserve the common volume title."""
    page = context.new_page()
    page.goto(site)
    page.get_by_role("status").filter(has_text="und 7 Data Stories").wait_for(timeout=LOAD_TIMEOUT)
    reference = FIXTURE["story_references"][-1]
    search(page, "Digitalisierung der Einwohnerkontrolle in Basel")
    link = page.locator(f'ol.sgb-results a[href="{reference["expected_url"]}"]')
    link.wait_for(timeout=MODEL_TIMEOUT)
    assert (link.get_attribute("aria-label") or "").startswith("Originalstory öffnen:")
    assert link.get_attribute("rel") == "noopener noreferrer"
    assert link.get_attribute("target") == "_blank"
    result = page.locator("ol.sgb-results li").filter(
        has=page.locator(f'a[href="{reference["expected_url"]}"]')
    )
    assert result.get_by_role("heading").inner_text().endswith(" — Data Stories")
    assert "Nur Zusammenfassung" not in result.inner_text()
    links = page.locator("ol.sgb-results a").evaluate_all("links => links.map(link => link.href)")
    assert len(links) == len(set(links)) <= 5
    result.screenshot(path=str(tmp_path / "story-result-desktop.png"))
    for width in (390, 320):
        page.set_viewport_size({"width": width, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        result.screenshot(path=str(tmp_path / f"story-result-{width}.png"))
    page.close()


def test_modes_keep_the_query_and_work_without_the_model(
    context: BrowserContext, site: str
) -> None:
    """The lexical mode needs no model. The combined mode falls back. A retry recovers."""
    assert context.browser is not None
    fresh = context.browser.new_context()  # An empty cache, so that the model must download.
    errors: list[str] = []
    page = open_page(fresh, set(), errors)
    model_requests: list[str] = []
    page.on("request", lambda request: model_requests.append(request.url))

    def block(route: Route) -> None:
        route.abort()

    page.route("https://huggingface.co/**", block)
    page.goto(site)
    page.get_by_role("status").filter(has_text="Forschungsbände").wait_for(timeout=LOAD_TIMEOUT)
    field = page.get_by_role("textbox", name="Wonach suchst du in Basels Geschichte?")
    notice = page.get_by_text("Das Sprachmodell ist nicht verfügbar.")
    failure = page.get_by_text("Die Suche ist fehlgeschlagen.")

    # Lexical mode: results without any model request.
    choose_mode(page, "Lexikalisch")
    search(page, "Merian")
    page.locator("ol.sgb-results li").first.wait_for(timeout=LOAD_TIMEOUT)
    lexical_links = result_links(page)
    assert 1 <= len(lexical_links) == len(set(lexical_links)) <= 5
    assert not [url for url in model_requests if is_model_request(url)]
    assert notice.count() == failure.count() == 0

    # Combined mode with the model blocked: lexical results, a short notice, and a retry button.
    choose_mode(page, "Kombiniert")
    notice.wait_for(timeout=MODEL_TIMEOUT)
    assert field.input_value() == "Merian"
    assert result_links(page) == lexical_links
    assert (
        page.get_by_role("status").filter(has_text="Das Sprachmodell ist nicht verfügbar").count()
    )
    assert page.get_by_role("button", name="Erneut versuchen").is_visible()

    # Semantic mode with the model blocked: the error, a hint about the lexical mode, and a retry.
    choose_mode(page, "Semantisch")
    failure.wait_for(timeout=MODEL_TIMEOUT)
    assert notice.count() == 0
    assert field.input_value() == "Merian"
    assert page.get_by_text("Die lexikalische Suche braucht das Sprachmodell nicht.").is_visible()
    assert page.locator("ol.sgb-results").count() == 0
    assert page.get_by_role("alert").filter(has_text="Die Suche ist fehlgeschlagen.").count() == 1

    # The retry button recovers once the model loads.
    page.unroute("https://huggingface.co/**", block)
    page.get_by_role("button", name="Erneut versuchen").press("Enter")
    page.locator("ol.sgb-results li").first.wait_for(timeout=MODEL_TIMEOUT)
    assert failure.count() == 0
    assert field.input_value() == "Merian"
    assert any(is_model_request(url) for url in model_requests)

    # Back in combined mode: no notice, and results for the same query.
    choose_mode(page, "Kombiniert")
    notice.wait_for(state="detached", timeout=MODEL_TIMEOUT)
    page.locator("ol.sgb-results li").first.wait_for(timeout=MODEL_TIMEOUT)
    assert field.input_value() == "Merian"
    assert 1 <= len(result_links(page)) <= 5

    # Lexical mode again: the same results as the first time.
    choose_mode(page, "Lexikalisch")
    wait_for_links(page, lexical_links)
    assert field.input_value() == "Merian"
    assert not errors
    fresh.close()


def test_local_versions_match_the_pyodide_lockfile(context: BrowserContext, site: str) -> None:
    """The site loads its packages from a Pyodide lockfile. Tests must run the same versions.

    The pins in `pyproject.toml` and the installed packages must equal the lockfile that the
    exported site requests. A new marimo release can move the lockfile. Then this test fails.
    """
    page = context.new_page()
    lock_urls: list[str] = []
    page.on(
        "request",
        lambda request: (
            lock_urls.append(request.url) if "pyodide-lock.json" in request.url else None
        ),
    )
    page.goto(site)
    page.get_by_role("status").filter(has_text="Forschungsbände").wait_for(timeout=LOAD_TIMEOUT)
    assert lock_urls, "The site did not request a Pyodide lockfile."
    response = page.request.get(lock_urls[0])
    assert response.ok, response.status
    lockfile = response.json()
    page.close()
    lock = {
        name.lower().replace("_", "-"): item["version"]
        for name, item in lockfile["packages"].items()
    }
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    pins = [*project["project"]["dependencies"], *project["tool"]["uv"]["constraint-dependencies"]]
    mismatches: list[str] = []
    checked: set[str] = set()
    for pin in pins:
        name, _, version = pin.partition("==")
        if name == "bm25s":  # A PyPI package. The PEP 723 header of app.py pins it.
            continue
        checked.add(name)
        installed = importlib.metadata.version(name)
        if not (lock.get(name) == version == installed):
            mismatches.append(
                f"{name}: lockfile {lock.get(name)}, pin {version}, installed {installed}"
            )
    assert not mismatches, mismatches
    assert {"marimo", "numpy", "pydantic", "pydantic-core"} <= checked
    assert (
        lockfile["info"]["python"].rsplit(".", 1)[0]
        == f"{sys.version_info[0]}.{sys.version_info[1]}"
    )


def test_comparison_saved_queries_navigation_and_filters(
    context: BrowserContext, site: str
) -> None:
    """The public comparison uses saved data and links back to the search."""
    page = context.new_page()
    requests: list[str] = []
    errors: list[str] = []
    page.on("request", lambda request: requests.append(request.url))
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(site + "vergleich.html")
    expect(page.get_by_role("heading", name="Suchmodi vergleichen", exact=True)).to_be_visible(
        timeout=LOAD_TIMEOUT
    )
    expect(page.get_by_role("combobox", name="Beispielfrage", exact=True)).to_be_visible(
        timeout=LOAD_TIMEOUT
    )
    assert page.locator("html").get_attribute("lang") == "de-CH"
    assert page.title() == "Suchmodi vergleichen | Frag mich was – Stadt.Geschichte.Basel"
    assert (
        page.locator(".sgb-brand").evaluate("el => getComputedStyle(el).backgroundColor")
        == "rgb(58, 30, 62)"
    )
    assert "Euclid Circular B" in page.locator("body").evaluate(
        "el => getComputedStyle(el).fontFamily"
    )
    assert page.get_by_role("textbox").count() == 0
    expect(page.get_by_role("heading", name="Was der Vergleich zeigt", exact=True)).to_be_visible()
    expect(page.locator(".sgb-insights")).to_contain_text("18 von 18")
    expect(page.locator(".sgb-insights")).to_contain_text("Schweizerhalle")

    page.get_by_role("combobox", name="Fragetyp", exact=True).select_option(label="Mehrere Quellen")
    expect(page.get_by_text("4 Fragen passen zu den Filtern.", exact=False)).to_be_visible()
    reference = FIXTURE["comparison_references"][-1]
    page.get_by_role("combobox", name="Beispielfrage", exact=True).select_option(
        label=reference["query"]
    )
    expected = page.locator(".sgb-expected a")
    expect(expected).to_have_count(2)
    expect(expected.first).to_have_attribute("href", reference["expected_urls"][0])
    assert (
        expected.evaluate_all("links => links.map(link => link.href)") == reference["expected_urls"]
    )
    expect(page.locator(".sgb-comparison-results section")).to_have_count(3)
    assert not any(
        "embeddings.json" in url or "huggingface" in url or ".onnx" in url or "transformers" in url
        for url in requests
    )
    assert any("/frag-mich-was/public/comparison.json" in url for url in requests)
    assert errors == []

    page.get_by_role("combobox", name="Fragetyp", exact=True).select_option(
        label="Andere Formulierungen"
    )
    page.get_by_role("combobox", name="Thema", exact=True).select_option(label="Schweizerhalle")
    expect(page.get_by_text("Keine Fragen passen zu den Filtern.", exact=False)).to_be_visible()
    expect(page.get_by_role("combobox", name="Beispielfrage", exact=True)).to_have_count(0)
    page.get_by_role("combobox", name="Fragetyp", exact=True).select_option(label="Alle")
    page.get_by_role("combobox", name="Thema", exact=True).select_option(label="Alle")
    expect(page.get_by_text("44 Fragen passen zu den Filtern.", exact=False)).to_be_visible()
    page.get_by_role("checkbox", name="Nur Fragen mit fehlenden Quellen in den Top 3").check()
    expect(page.get_by_text("44 Fragen passen zu den Filtern.", exact=False)).to_have_count(0)

    page.set_viewport_size({"width": 390, "height": 844})
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    columns = page.locator(".sgb-comparison-results").evaluate(
        "el => getComputedStyle(el).gridTemplateColumns"
    )
    assert len(columns.split()) == 1
    back = page.locator(".sgb-brand").get_by_role("link", name="Zur Suche", exact=True)
    page.locator(".sgb-brand a").first.focus()
    page.keyboard.press("Tab")
    assert back.evaluate("el => el.getRootNode().activeElement === el")
    assert back.evaluate("el => getComputedStyle(el).outlineStyle") != "none"
    back.press("Enter")
    expect(page.get_by_role("heading", name="Frag mich was", exact=True)).to_be_visible(
        timeout=LOAD_TIMEOUT
    )
    page.get_by_text("Über die Suche", exact=True).click()
    comparison_link = page.locator(".sgb-about").get_by_role(
        "link", name="Suchmodi vergleichen", exact=True
    )
    expect(comparison_link).to_have_attribute("href", "vergleich.html")
    comparison_link.click()
    expect(page.get_by_role("heading", name="Suchmodi vergleichen", exact=True)).to_be_visible(
        timeout=LOAD_TIMEOUT
    )
    page.close()


def test_comparison_report_failure_is_explained_in_german(
    context: BrowserContext, site: str
) -> None:
    page = context.new_page()
    page.route(
        "**/public/comparison.json",
        lambda route: route.fulfill(status=200, body='{"schema_version":99}'),
    )
    page.goto(site + "vergleich.html")
    expect(page.get_by_role("alert")).to_contain_text(
        "Der Vergleich ist nicht verfügbar.", timeout=LOAD_TIMEOUT
    )
    expect(
        page.locator(".sgb-brand").get_by_role("link", name="Zur Suche", exact=True)
    ).to_be_visible()
    assert page.get_by_role("combobox", name="Beispielfrage", exact=True).count() == 0
    page.close()
