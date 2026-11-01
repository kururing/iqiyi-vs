"""Run with the checkout Python: repeated artwork loads and related UI refresh regressions."""
from collections import Counter
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import subtitle_app as app
from iqiyi_common import HEADLESS_BROWSER_ARGS
from playwright.sync_api import sync_playwright


def episode(number, title):
    return {"tvid": str(number), "provider": "iqiyi", "albumId": str(number * 100),
            "albumTitle": title, "albumCoverUrl": f"https://pic3.iqiyipic.com/{number}.jpg",
            "order": 1, "downloaded": False, "cues": 0}


rows = [episode(1, "Phim chính"), episode(2, "Phim phụ")]
requests = Counter()
checks = {}


def api(route):
    path = urlsplit(route.request.url).path
    if path == "/":
        route.fulfill(content_type="text/html", body=app.PAGE.replace("__IQIYI_TOKEN__", '"fixture"'))
    else:
        payload = {"episodes": rows} if path == "/api/episodes" else {}
        route.fulfill(content_type="application/json", body=json.dumps(payload))


def image(route):
    path = urlsplit(route.request.url).path
    requests[path] += 1
    if "broken" in path:
        route.abort()
    else:
        route.fulfill(content_type="image/svg+xml", headers={"Cache-Control": "no-store"},
                      body='<svg xmlns="http://www.w3.org/2000/svg" width="72" height="108"><rect width="72" height="108" fill="#207455"/></svg>')


with sync_playwright() as pw:
    browser = pw.chromium.launch(channel="msedge", headless=True, args=list(HEADLESS_BROWSER_ARGS))
    try:
        page = browser.new_page(viewport={"width": 1280, "height": 850})
        page.add_init_script("""const originalInterval = window.setInterval;
          window.setInterval = (fn, delay, ...args) => delay === 5000 ? 0 : originalInterval(fn, delay, ...args);""")
        page.route("http://127.0.0.1:18766/**", api)
        page.route("https://pic3.iqiyipic.com/**", image)
        page.goto("http://127.0.0.1:18766/")
        page.wait_for_function("document.querySelectorAll('#items img').length === 2 && [...document.querySelectorAll('#items img')].every(n=>n.naturalWidth>0)")
        page.evaluate("window.originalCover=document.querySelector('#items img');window.coverLoads=0;originalCover.addEventListener('load',()=>coverLoads++)")
        initial = requests.copy()
        for n in range(4):
            rows[0]["downloadProgress"] = {"stage": "downloading", "message": f"Tiến độ {n}"}
            page.evaluate("refresh(true)")
        page.wait_for_timeout(100)
        checks["progress_keeps_loaded_images"] = requests == initial and page.evaluate("coverLoads===0")

        rows.reverse()
        page.evaluate("refresh(true)")
        page.wait_for_timeout(100)
        checks["reorder_keeps_loaded_images"] = requests == initial and page.evaluate("coverLoads===0")

        page.locator("#libraryQuery").fill("Phim phụ")
        checks["filter_keeps_cover_connected"] = page.evaluate("originalCover.isConnected")
        page.locator("#libraryQuery").fill("")
        page.wait_for_timeout(100)
        checks["filter_clear_does_not_refetch"] = requests == initial and page.evaluate("coverLoads===0")

        page.locator(".albumHeading").first.click()
        page.locator(".episodeLegendHelp").first.evaluate("node=>node.open=true")
        page.evaluate("refresh(true)")
        checks["refresh_preserves_open_help"] = page.locator(".episodeLegendHelp").first.evaluate("node=>node.open")

        page.evaluate("""toggleSearch();searchMoviesData=[{albumId:'300',title:'Phim khác'}];renderMovieSearchResults();
          window.searchButton=document.querySelector('#movieSearchResults button');searchButton.focus()""")
        page.evaluate("refresh(true)")
        checks["search_button_keeps_focus"] = page.evaluate("searchButton.isConnected && document.activeElement===searchButton")

        rows[0]["albumCoverUrl"] = "https://pic3.iqiyipic.com/broken-ảnh.jpg"
        page.evaluate("refresh(true)")
        page.wait_for_timeout(100)
        failed_count = sum(value for key, value in requests.items() if "broken" in key)
        for _ in range(4):
            page.evaluate("refresh(true)")
            page.wait_for_timeout(40)
        checks["normalized_failed_url_is_not_retried"] = sum(value for key, value in requests.items() if "broken" in key) == failed_count

        rows[0]["albumCoverUrl"] = "https://pic3.iqiyipic.com/replacement.jpg"
        page.evaluate("refresh(true)")
        page.wait_for_function("document.querySelector('#items img[src$=\"replacement.jpg\"]')?.naturalWidth>0")
        checks["changed_url_loads_once"] = requests["/replacement.jpg"] == 1
        preview = Path(__file__).resolve().parents[1] / ".tmp/cover-refresh"
        preview.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(preview / "desktop.png"))
        page.set_viewport_size({"width": 375, "height": 812})
        checks["mobile_has_no_overflow"] = page.evaluate("document.documentElement.scrollWidth<=innerWidth")
        page.screenshot(path=str(preview / "mobile.png"))
        print(json.dumps({"checks": checks, "requests": dict(requests)}, ensure_ascii=True))
        assert all(checks.values()), "Refresh regressions: " + ", ".join(name for name, ok in checks.items() if not ok)
    finally:
        browser.close()
