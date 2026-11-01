"""Manager movie search follows the app's verified title lookup and suggestion flow."""
import json
from pathlib import Path
import sys
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import subtitle_app as app
from iqiyi_common import HEADLESS_BROWSER_ARGS
from playwright.sync_api import sync_playwright, expect

suggestions, searches, additions, held, episodes = [], [], [], {}, []
first = {"title": "Dữ Tấn Trường An", "query": "与晋长安", "year": "2025"}
second = {"title": "Ninh An Như Mộng", "query": "宁安如梦", "year": "2023"}


def route_request(route):
    parsed = urlsplit(route.request.url)
    query = parse_qs(parsed.query).get("q", [""])[0]
    if parsed.path == "/":
        route.fulfill(content_type="text/html", body=app.PAGE.replace("__IQIYI_TOKEN__", '"fixture"'))
        return
    payload = {}
    if parsed.path == "/api/episodes":
        payload = {"episodes": episodes}
    elif parsed.path == "/api/app-localization":
        payload = {"installed": True, "status": "idle"}
    elif parsed.path == "/api/international-search":
        suggestions.append(query)
        if query == "slow old":
            held["suggestions"] = route
            return
        if query == "nguon hong":
            route.fulfill(status=503, json={"error": "Không kết nối được iq.com"})
            return
        payload = {"query": query, "title": query, "suggestions": []}
        if query in ("du tan truong an", first["title"]):
            payload.update(query=first["query"], title=first["title"])
        elif query in ("du tan", "nhap IME"):
            payload["suggestions"] = [first]
        elif query == "phim":
            payload["suggestions"] = [first, second]
        elif query == "html":
            payload["suggestions"] = [{"title": '<img src=x onerror="alert(1)">', "query": "测试剧"}]
    elif parsed.path == "/api/search":
        searches.append(query)
        if query == "slow search":
            held["search"] = route
            return
        identifier = "800" if query == first["query"] else "900"
        payload = {"results": [{"albumId": identifier, "title": query, "year": "2025"}]}
    elif parsed.path == "/api/album/add":
        data = json.loads(route.request.post_data)
        additions.append(data)
        episodes.append({"provider": "iqiyi", "tvid": "12345678", "albumId": data["albumId"],
                         "albumTitle": data["title"], "order": 1})
        payload = {"message": "Đã thêm phim vào thư viện."}
    route.fulfill(json=payload)


with sync_playwright() as pw:
    browser = pw.chromium.launch(channel="msedge", headless=True, args=list(HEADLESS_BROWSER_ARGS))
    try:
        page = browser.new_page(viewport={"width": 1200, "height": 850})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        # Deliberately let two old replies complete after cancellation to test stale-response guards.
        page.add_init_script("""const realFetch=window.fetch;
          window.finishedOld=[];
          window.fetch=(url,options={})=>{
            if(/q=slow%20(?:old|search)/.test(String(url))){options={...options};delete options.signal;
              return realFetch(url,options).then(r=>{finishedOld.push(String(url));return r})}
            return realFetch(url,options)
          };""")
        page.route("http://127.0.0.1:18766/**", route_request)
        page.goto("http://127.0.0.1:18766/")
        page.locator("#addMovieButton").click()
        field = page.locator("#movieQuery")
        popup = page.locator("#movieSuggestions")
        results = page.locator("#movieSearchResults")
        field.fill("du")
        field.fill("du tan")
        field.fill("du tan truong an")
        expect(popup.get_by_role("button", name=first["title"], exact=True)).to_be_visible()
        assert suggestions == ["du tan truong an"], suggestions
        expect(field).to_be_focused()
        assert searches == [], "Typing offers suggestions without starting a movie search"
        field.press("Enter")
        expect(results.locator(".searchResultTitle")).to_have_text(first["title"])
        assert searches == [first["query"]], searches
        results.get_by_role("button", name="Thêm phim", exact=True).click()
        expect(results.get_by_role("button", name="Trong thư viện")).to_be_disabled()
        assert additions == [{"albumId": "800", "title": first["query"]}], additions

        before = len(suggestions)
        field.fill("其他剧")
        field.press("Enter")
        expect(results.locator(".searchResultTitle")).to_have_text("其他剧")
        assert len(suggestions) == before, "Chinese names go directly to iQIYI"

        field.fill("phim")
        field.press("Enter")
        expect(popup.get_by_role("button").first).to_be_focused()
        assert searches[-1] == "其他剧", "Ambiguous names must not choose the first movie silently"
        page.keyboard.press("ArrowDown")
        expect(popup.get_by_role("button").nth(1)).to_be_focused()
        page.keyboard.press("Enter")
        expect(results.locator(".searchResultTitle")).to_have_text(second["title"])
        assert searches[-1] == second["query"]
        expect(field).to_have_value(second["title"])

        field.fill("du tan")
        expect(popup.get_by_role("button")).to_be_visible()
        field.press("ArrowDown")
        expect(popup.get_by_role("button")).to_be_focused()
        page.keyboard.press("Escape")
        expect(popup).to_be_hidden()
        expect(field).to_be_focused()
        page.wait_for_timeout(350)
        expect(popup).to_be_hidden()

        before = len(suggestions)
        field.evaluate("el=>{el.value='nhap IME';el.dispatchEvent(new CompositionEvent('compositionstart',{bubbles:true}));el.dispatchEvent(new InputEvent('input',{bubbles:true,isComposing:true}))}")
        page.wait_for_timeout(350)
        assert len(suggestions) == before
        field.dispatch_event("compositionend")
        expect(popup.get_by_role("button")).to_be_visible()

        field.fill("slow old")
        page.wait_for_function("document.querySelector('#movieQuery').getAttribute('aria-busy')==='true'")
        page.wait_for_timeout(40)
        field.fill("du tan")
        expect(popup.get_by_role("button")).to_have_text(first["title"] + " · 2025")
        held.pop("suggestions").fulfill(json={"query": "slow old", "suggestions": [second]})
        page.wait_for_function("finishedOld.some(x=>x.includes('slow%20old'))")
        expect(popup.get_by_role("button")).to_have_text(first["title"] + " · 2025")

        field.fill("slow search")
        field.press("Enter")
        page.wait_for_function("document.querySelector('#movieSearchForm').getAttribute('aria-busy')==='true'")
        page.wait_for_timeout(60)
        assert "search" in held
        field.fill("其他剧")
        field.press("Enter")
        expect(results.locator(".searchResultTitle")).to_have_text("其他剧")
        held.pop("search").fulfill(json={"results": [{"albumId": "111", "title": "Kết quả cũ"}]})
        page.wait_for_function("finishedOld.some(x=>x.includes('slow%20search'))")
        expect(results.locator(".searchResultTitle")).to_have_text("其他剧")

        field.fill("nguon hong")
        field.press("Enter")
        expect(results.locator(".searchResultTitle")).to_have_text("nguon hong")
        expect(page.locator("#movieSearchButton")).to_be_enabled()
        assert searches[-1] == "nguon hong", "Unavailable iq.com suggestions must not block ordinary search"
        field.fill("html")
        expect(popup.get_by_role("button")).to_have_text('<img src=x onerror="alert(1)">')
        expect(popup.locator("img")).to_have_count(0)
        field.fill("phim")
        expect(popup.get_by_role("button")).to_have_count(2)
        output = Path(__file__).resolve().parents[1] / ".tmp/manager-search"
        output.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(output / "desktop.png"))
        page.set_viewport_size({"width": 375, "height": 812})
        assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
        box = popup.bounding_box()
        assert box and box["x"] >= 0 and box["x"] + box["width"] <= 375
        page.screenshot(path=str(output / "mobile.png"))
        page.locator("#addMovieButton").click()
        expect(popup).to_be_hidden()
        expect(field).to_have_value("")
        assert not errors, errors
    finally:
        browser.close()
print("PASS: manager search shares title lookup; debounce, IME, keyboard, exact/ambiguous names, stale replies, add, fallback and mobile work")
