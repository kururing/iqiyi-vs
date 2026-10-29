"""Offline Edge check: first installation entry and dark menu contrast."""
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import subtitle_app as app
from iqiyi_common import HEADLESS_BROWSER_ARGS
from playwright.sync_api import sync_playwright, expect

installed = False
actions = []
cover_url = ""
discovery_rows = []
discovery_decisions = []

def route_request(route):
    path = urlsplit(route.request.url).path
    if path == "/":
        route.fulfill(content_type="text/html", body=app.PAGE.replace("__IQIYI_TOKEN__", '"fixture-token"'))
        return
    payload = {}
    if path == "/api/app-localization":
        if route.request.method == "POST":
            actions.append(json.loads(route.request.post_data)["action"])
        payload = {"status": "idle", "installed": installed}
    elif path == "/api/episodes":
        payload = {"episodes": [{"tvid": "1", "provider": "iqiyi", "albumId": "100",
                    "albumTitle": "Phim kiểm tra", "albumCoverUrl": cover_url,
                    "order": 1, "downloaded": False, "cues": 0}], "discoveries": discovery_rows}
    elif path == "/api/discoveries/decide":
        decision = json.loads(route.request.post_data)
        discovery_decisions.append(decision)
        discovery_rows[:] = [row for row in discovery_rows if row["tvid"] != decision["tvid"]]
        payload = {"message": "Đã cập nhật thông báo."}
    route.fulfill(content_type="application/json", body=json.dumps(payload))

with sync_playwright() as pw:
    browser = pw.chromium.launch(channel="msedge", headless=True, args=list(HEADLESS_BROWSER_ARGS))
    try:
        page = browser.new_page(viewport={"width": 1280, "height": 850})
        page.route("http://127.0.0.1:18766/**", route_request)
        page.goto("http://127.0.0.1:18766/")
        expect(page.locator("#integrationPrompt")).to_be_visible()
        expect(page.locator(".albumCover")).to_be_visible()
        expect(page.locator(".albumCover img")).to_have_count(0)
        page.route("https://pic3.iqiyipic.com/poster.jpg", lambda route: route.fulfill(
            content_type="image/svg+xml", body='<svg xmlns="http://www.w3.org/2000/svg" width="72" height="108"><rect width="72" height="108" fill="#207455"/></svg>'))
        cover_url = "https://pic3.iqiyipic.com/poster.jpg"
        page.evaluate("refresh(false)")
        expect(page.locator(".albumCover img")).to_have_attribute("src", cover_url)
        page.wait_for_function("document.querySelector('.albumCover img')?.naturalWidth > 0")
        expect(page.get_by_role("button", name="Chọn tập", exact=True)).to_have_count(0)
        page.locator(".albumCover").click()
        expect(page.locator(".episodeList")).to_be_visible()
        expect(page.locator(".albumHeading")).to_have_attribute("aria-expanded", "true")
        page.locator(".albumHeading").press("Space")
        expect(page.locator(".episodeList")).to_be_hidden()
        expect(page.locator(".albumHeading")).to_be_focused()
        page.locator(".albumHeading").press("Enter")
        expect(page.locator(".episodeList")).to_be_visible()
        page.locator(".seriesTitle").click()
        expect(page.locator(".episodeList")).to_be_hidden()
        page.locator(".albumHeading").click()
        for width, height in ((1280, 850), (375, 812), (812, 375)):
            page.set_viewport_size({"width": width, "height": height})
            assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
            assert page.locator(".albumHeading").evaluate("n=>n.getBoundingClientRect().right<=innerWidth")
        page.set_viewport_size({"width": 1280, "height": 850})
        page.route("https://pic3.iqiyipic.com/broken.jpg", lambda route: route.abort())
        cover_url = "https://pic3.iqiyipic.com/broken.jpg"
        page.evaluate("refresh(false)")
        expect(page.locator(".albumCover img")).to_have_count(0)
        expect(page.locator(".albumCover svg")).to_be_visible()
        expect(page.locator(".episodeList")).to_be_visible()
        page.locator("#integrationPrompt button").click()
        expect(page.locator("#appSettings")).to_be_visible()
        expect(page.locator("#localizeIqiyiButton")).to_be_enabled()
        expect(page.locator("#iqiyiIntegration")).to_be_in_viewport()
        page.keyboard.press("Escape")
        page.locator(".menu summary").first.click()
        menu = page.locator(".moreMenu").first
        expect(menu).to_be_visible()
        expect(page.locator(".episodeList")).to_be_visible()
        colors = menu.locator("button").evaluate_all("nodes=>nodes.map(n=>getComputedStyle(n).color)")
        assert colors == ["rgb(240, 243, 245)", "rgb(255, 183, 189)"], colors
        installed = True
        page.evaluate("refreshAppLocalization()")
        expect(page.locator("#integrationPrompt")).to_be_hidden()
        expect(page.locator("#localizeIqiyiButton")).to_have_text("Đã cài đặt")
        expect(page.locator("#localizeIqiyiButton")).to_be_disabled()
        page.evaluate("openIntegrationSettings()")
        page.locator("#updateIqiyiButton").click()
        expect(page.locator("#updateIqiyiButton")).to_be_enabled()
        assert actions == ["repair"], actions
        page.keyboard.press("Escape")
        page.set_viewport_size({"width": 375, "height": 812})
        installed = False
        page.evaluate("refreshAppLocalization()")
        expect(page.locator("#integrationPrompt")).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
        page.evaluate("window.pywebview={}; window.open=url=>window.connectionUrl=url; loginIqcom()")
        assert page.evaluate("window.connectionUrl") == "http://127.0.0.1:18766/?connect=iqcom"
        discovery_rows[:] = [
            {"tvid": "20", "title": "Phim vừa nhận diện có tên dài để kiểm tra xuống dòng",
             "originalTitle": "测试电影", "episodes": 2, "albumCoverUrl": ""},
            {"tvid": "30", "title": "Phim chưa có ảnh", "episodes": 1}]
        page.evaluate("refresh(false)")
        page.locator("#notificationsButton").click()
        notifications = page.locator("#notificationsDialog")
        expect(notifications).to_be_visible()
        expect(notifications.locator(".albumCover")).to_have_count(2)
        expect(notifications.locator(".albumCover img")).to_have_count(0)
        discovery_rows[0]["albumCoverUrl"] = "https://pic3.iqiyipic.com/poster.jpg"
        page.evaluate("refresh(false)")
        page.wait_for_function("document.querySelector('#notificationsList img')?.naturalWidth > 0")
        preview = Path(__file__).resolve().parents[1] / ".tmp" / "discovery-covers"
        preview.mkdir(parents=True, exist_ok=True)
        for width, height in ((1280, 850), (375, 812), (812, 375)):
            page.set_viewport_size({"width": width, "height": height})
            assert notifications.evaluate("node=>node.scrollWidth<=node.clientWidth")
            assert notifications.locator(".discoveryActions").evaluate_all(
                "nodes=>nodes.every(n=>n.getBoundingClientRect().right<=innerWidth)")
            page.screenshot(path=str(preview / f"notifications-{width}.png"))
        discovery_rows[0]["albumCoverUrl"] = "https://pic3.iqiyipic.com/broken.jpg"
        page.evaluate("refresh(false)")
        expect(notifications.locator(".albumCover img")).to_have_count(0)
        expect(notifications.locator(".albumCover svg")).to_have_count(2)
        notifications.get_by_role("button", name="Chấp nhận", exact=True).first.click()
        expect(notifications.locator(".searchResult")).to_have_count(1)
        notifications.get_by_role("button", name="Bỏ qua", exact=True).click()
        expect(notifications.locator(".searchResult")).to_have_count(0)
        assert discovery_decisions == [{"tvid": "20", "action": "accept"}, {"tvid": "30", "action": "dismiss"}]
        page.keyboard.press("Escape")
        page.goto("http://127.0.0.1:18766/?connect=iqcom")
        expect(page.locator("#appSettings")).to_be_visible()
        print("PASS: covers refresh asynchronously; missing/broken images fall back; episode selection works; responsive layouts have no overflow; setup and menus work")
    finally:
        browser.close()
