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
cover_requests = []
download_progress = {}
discovery_rows = []
discovery_decisions = []
iqcom_state = {}
iqcom_login_calls = []
localization_state = {"status": "idle"}

def route_request(route):
    global installed
    path = urlsplit(route.request.url).path
    if path == "/":
        route.fulfill(content_type="text/html", body=app.PAGE.replace("__IQIYI_TOKEN__", '"fixture-token"'))
        return
    payload = {}
    if path == "/api/app-localization":
        if route.request.method == "POST":
            action = json.loads(route.request.post_data)["action"]
            actions.append(action)
            installed = action != "restore"
        payload = {**localization_state, "installed": installed}
    elif path == "/api/episodes":
        payload = {"episodes": [{"tvid": "1", "provider": "iqiyi", "albumId": "100",
                    "albumTitle": "Phim kiểm tra", "albumCoverUrl": cover_url,
                    "order": 1, "downloaded": False, "cues": 0, "downloadProgress": download_progress}], "discoveries": discovery_rows, "iqcomSession": iqcom_state}
    elif path == "/api/iqcom-login":
        iqcom_login_calls.append(route.request.method)
        iqcom_state.update(loginPending=True, message="Đăng nhập trong cửa sổ iq.com vừa mở.")
        payload = iqcom_state
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
        def poster(route):
            cover_requests.append(route.request.url)
            route.fulfill(content_type="image/svg+xml", headers={"Cache-Control": "no-store"},
                body='<svg xmlns="http://www.w3.org/2000/svg" width="72" height="108"><rect width="72" height="108" fill="#207455"/></svg>')
        page.route("https://pic3.iqiyipic.com/poster.jpg", poster)
        cover_url = "https://pic3.iqiyipic.com/poster.jpg"
        page.evaluate("refresh(false)")
        expect(page.locator(".albumCover img")).to_have_attribute("src", cover_url)
        page.wait_for_function("document.querySelector('.albumCover img')?.naturalWidth > 0")
        page.evaluate("window.savedCover=document.querySelector('#items .albumCover img');window.coverLoads=0;savedCover.addEventListener('load',()=>coverLoads++)")
        request_count = len(cover_requests)
        for progress in range(4):
            download_progress.update(stage="running", message=f"Đang tải {progress}")
            page.evaluate("refresh(false)")
            assert page.evaluate("savedCover===document.querySelector('#items .albumCover img')"), "Progress updates replaced the loaded cover"
            assert page.evaluate("savedCover.complete && savedCover.naturalWidth>0")
        page.evaluate("refresh(true)")
        assert page.evaluate("savedCover===document.querySelector('#items .albumCover img')")
        assert page.evaluate("coverLoads") == 0, "Repainting must not reload a completed image"
        assert len(cover_requests) == request_count, "Unchanged artwork must not be fetched again"
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
        assert page.evaluate("savedCover===document.querySelector('#items .albumCover img')")
        assert page.evaluate("coverLoads") == 0
        assert len(cover_requests) == request_count, "Opening or selecting episodes must preserve loaded artwork"
        page.evaluate("episodeData[0].downloaded=true;episodeData[0].cues=8;render(episodeData)")
        expect(page.locator(".albumSummary").first).to_contain_text("1 đã tải")
        assert page.evaluate("savedCover===document.querySelector('#items .albumCover img')")
        for width, height in ((1280, 850), (375, 812), (812, 375)):
            page.set_viewport_size({"width": width, "height": height})
            assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
            assert page.locator(".albumHeading").evaluate("n=>n.getBoundingClientRect().right<=innerWidth")
        page.set_viewport_size({"width": 1280, "height": 850})
        broken_requests = []
        def broken_poster(route):
            broken_requests.append(route.request.url)
            route.abort()
        page.route("https://pic3.iqiyipic.com/broken.jpg", broken_poster)
        cover_url = "https://pic3.iqiyipic.com/broken.jpg"
        page.evaluate("refresh(false)")
        expect(page.locator(".albumCover img")).to_have_count(0)
        expect(page.locator(".albumCover svg")).to_be_visible()
        failed_request_count = len(broken_requests)
        for _ in range(3):
            page.evaluate("refresh(true)")
        assert len(broken_requests) == failed_request_count, "Failed images must keep the placeholder without retrying on every refresh"
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
        page.evaluate("openIntegrationSettings()")
        expect(page.locator("#iqiyiIntegrationStatus")).to_have_text("Chưa kết nối")
        expect(page.locator("#localizeIqiyiButton")).to_have_text("Kết nối app iQIYI")
        expect(page.locator("#localizeIqiyiButton")).to_be_enabled()
        expect(page.locator("#iqiyiIntegration .settingsHint")).to_have_count(1)
        expect(page.locator("#iqiyiIntegration button")).to_have_count(2)
        preview = Path(__file__).resolve().parents[1] / ".tmp" / "integration-buttons"
        preview.mkdir(parents=True, exist_ok=True)
        page.locator("#iqiyiIntegration").screenshot(path=str(preview / "disconnected.png"))
        page.locator("#localizeIqiyiButton").click()
        expect(page.locator("#integrationPrompt")).to_be_hidden()
        expect(page.locator("#iqiyiIntegrationStatus")).to_have_text("Đã kết nối")
        expect(page.locator("#localizeIqiyiButton")).to_be_enabled()
        expect(page.locator("#localizeIqiyiButton")).to_have_text("Kết nối lại app iQIYI")
        expect(page.locator("#restoreIqiyiButton")).to_be_enabled()
        assert actions == ["apply"], actions
        page.locator("#iqiyiIntegration").screenshot(path=str(preview / "connected.png"))
        page.once("dialog", lambda dialog: dialog.dismiss())
        page.locator("#restoreIqiyiButton").click()
        assert actions == ["apply"], actions
        confirmations = []
        def confirm_removal(dialog):
            confirmations.append(dialog.message)
            dialog.accept()
        page.once("dialog", confirm_removal)
        page.locator("#restoreIqiyiButton").click()
        expect(page.locator("#iqiyiIntegrationStatus")).to_have_text("Chưa kết nối")
        expect(page.locator("#localizeIqiyiButton")).to_be_enabled()
        assert actions == ["apply", "restore"], actions
        assert "toàn bộ script" in confirmations[0] and "vẫn được giữ" not in confirmations[0]
        localization_state.update(status="running", message="Đang gỡ tích hợp…")
        page.evaluate("refreshAppLocalization()")
        expect(page.locator("#localizeIqiyiButton")).to_be_disabled()
        expect(page.locator("#restoreIqiyiButton")).to_be_disabled()
        expect(page.locator("#appLocalizationStatus")).to_have_attribute("aria-busy", "true")
        localization_state.update(status="error", message="Thao tác thất bại")
        page.evaluate("refreshAppLocalization()")
        expect(page.locator("#localizeIqiyiButton")).to_be_enabled()
        expect(page.locator("#restoreIqiyiButton")).to_be_enabled()
        expect(page.locator("#appLocalizationStatus")).to_have_class("error")
        localization_state.update(status="idle", message="")
        page.evaluate("refreshAppLocalization()")
        page.set_viewport_size({"width": 375, "height": 812})
        assert page.locator("#iqiyiIntegration").evaluate("n=>n.scrollWidth<=n.clientWidth")
        page.locator("#iqiyiIntegration").screenshot(path=str(preview / "mobile.png"))
        page.keyboard.press("Escape")
        page.set_viewport_size({"width": 375, "height": 812})
        installed = False
        page.evaluate("refreshAppLocalization()")
        expect(page.locator("#integrationPrompt")).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
        page.evaluate("window.pywebview={};window.open=()=>{throw Error('Must use the private login endpoint')};loginIqcom()")
        expect(page.locator("#iqcomLoginButton")).to_have_text("Đang chờ đăng nhập…")
        expect(page.locator("#iqcomLoginButton")).to_be_disabled()
        page.evaluate("loginIqcom()")
        assert iqcom_login_calls == ["POST"]
        iqcom_state.update(loginPending=False, connected=True, message="Đã nhận phiên từ trang đăng nhập iq.com.")
        page.evaluate("refresh(true)")
        expect(page.locator("#iqcomStatus")).to_have_text("Đã nhận phiên từ trang đăng nhập iq.com.")
        expect(page.locator("#iqcomLoginButton")).to_be_enabled()
        page.evaluate("""async()=>{
          delete window.pywebview;
          const receive=event=>{if(event.data?.type==='iqcom-session-check'){
            window.removeEventListener('message',receive);
            window.postMessage({type:'iqcom-session-result',requestId:event.data.requestId,
              state:{connected:true,message:'Phiên trình duyệt kiểm tra'}},location.origin);
          }};
          window.addEventListener('message',receive);
          await loginIqcom();
        }""")
        expect(page.locator("#iqcomStatus")).to_have_text("Phiên trình duyệt kiểm tra")
        assert iqcom_login_calls == ["POST"], "Web checks keep using the extension bridge"
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
        page.evaluate("window.savedDiscoveryCover=document.querySelector('#notificationsList img')")
        discovery_request_count = len(cover_requests)
        page.evaluate("discoveryBusy.add('20');renderDiscoveries()")
        expect(notifications.get_by_role("button", name="Chấp nhận", exact=True).first).to_be_disabled()
        page.evaluate("discoveryBusy.delete('20');renderDiscoveries()")
        assert page.evaluate("savedDiscoveryCover===document.querySelector('#notificationsList img')")
        assert len(cover_requests) == discovery_request_count

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
