"""Run with the checkout's Python; uses installed Edge for the UI check."""
import json
from pathlib import Path
import sys
import tempfile
from urllib.parse import urlsplit, parse_qs

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import subtitle_app as app
from iqiyi_common import HEADLESS_BROWSER_ARGS
from translation_pipeline import TranslationJobs
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
MEMORY = {"genre": "Cổ trang, có dấu hiệu tranh chấp trong triều.", "characters": [
    {"name_zh": "甲", "name_vi": "Giáp", "role": "Được gọi là bệ hạ trong đoạn đã phân tích."},
    {"name_zh": "乙", "name_vi": "Ất", "role": "Vị quan đang tâu việc."}],
    "pronoun_matrix": {"甲 to 乙": "trẫm / khanh", "乙 to 甲": "thần / bệ hạ"},
    "glossary": {"朝廷": "triều đình"}, "translation_style": "Giữ giọng trang trọng khi thiết triều.\nChưa đủ căn cứ cho quan hệ riêng tư."}
LEGACY = {"genre": "Hiện đại", "summary": "Hai đồng nghiệp bàn việc.", "style": "Lời thoại tự nhiên.",
          "pronouns": [{"speaker": "A", "listener": "B", "self": "tôi", "address": "anh", "evidence": "Câu 12 gọi đồng nghiệp."}],
          "glossary": [{"source": "项目", "target": "dự án", "note": "Thuật ngữ công việc."}]}
JOB1, JOB2 = "a" * 32, "b" * 32


def check_saved_job():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        jobs = TranslationJobs(root / "jobs")
        folder = jobs.folder(JOB1)
        folder.mkdir(parents=True)
        (folder / "status.json").write_text(json.dumps({"id": JOB1, "stage": "error"}), encoding="utf-8")
        episode = root / "episode"
        episode.mkdir()
        source = episode / "source.srt"
        source.write_text("1\n00:00:01,000 --> 00:00:02,000\n你好\n", encoding="utf-8")
        stat = source.stat()
        (episode / "translation-job.json").write_text(json.dumps({"id": JOB1, "source_signature": [stat.st_mtime_ns, stat.st_size]}))
        assert jobs.episode_status(episode)["memory_available"] is False
        raw = json.dumps(MEMORY, ensure_ascii=False).encode()
        (folder / "memory.json").write_bytes(raw)
        assert jobs.episode_status(episode)["memory_available"] is True
        assert jobs.artifact(JOB1, "memory.json") == raw  # Available before translation completes.
        source.write_text("changed", encoding="utf-8")
        assert jobs.episode_status(episode) is None  # Never display a stale source association.


def check_browser():
    episodes = [{"tvid": str(i), "provider": "iqiyi", "albumId": "100", "albumTitle": "测试", "albumTitleVi": "Phim kiểm tra", "order": i,
                 "downloaded": True, "cues": 5, "translation": {"id": job, "stage": "error", "message": "Đã lưu hồ sơ", "memory_available": True}}
                for i, job in [(1, JOB1), (2, JOB2)]]
    episodes[1]["translation"]["stage"] = "complete"
    for index, extra in [(3, {"downloaded": True, "cues": 5}),
                         (4, {"downloadProgress": {"stage": "access", "message": "Cần quyền xem."}}),
                         (5, {"downloadProgress": {"stage": "downloading"}}), (6, {})]:
        episodes.append({"tvid": str(index), "provider": "iqiyi", "albumId": "100", "albumTitle": "测试",
                         "albumTitleVi": "Phim kiểm tra", "order": index, "downloaded": False, "cues": 0, **extra})
    for index, title in enumerate(["Trường An ký", "Mùa hạ năm ấy", "Dấu vết cuối cùng", "Gặp lại ngày mai"], 10):
        episodes.append({"tvid": str(index), "provider": "iqiyi", "albumId": str(index), "albumTitle": title,
                         "order": 1, "downloaded": False, "cues": 0, "downloadAvailable": True})
    errors, downloads, unexpected = [], [], []
    state = {"fail": False, "models": [], "job1_stage": "error", "hold_status": False, "held": [], "starts": []}

    def route_handler(route):
        parsed = urlsplit(route.request.url)
        if parsed.path == "/":
            route.fulfill(content_type="text/html", body=app.PAGE.replace("__IQIYI_TOKEN__", '"test-token"'))
            return
        if parsed.path == "/favicon.ico":
            route.fulfill(content_type="image/x-icon", body=(ROOT / 'assets/iqiyi.ico').read_bytes())
            return
        if parsed.path == "/api/episodes":
            payload = {"episodes": episodes, "albums": {}, "discoveries": [], "session": {}, "iqcomSession": {}}
        elif parsed.path == "/api/translation/providers":
            payload = {"providers": app.TRANSLATION_PROVIDERS, "active_id": None}
        elif parsed.path == "/api/translation/models":
            payload = {"models": state["models"]}
        elif parsed.path == "/api/app-localization":
            payload = {"status": "idle"}
        elif parsed.path == "/api/iqiyi-proxy":
            payload = {"configured": False}
        elif parsed.path == "/api/translation/status":
            job_id = parse_qs(parsed.query)["id"][0]
            payload = {"id": job_id, "stage": "complete" if job_id == JOB2 else state["job1_stage"], "message": "Đã lưu", "episode_id": "2" if job_id == JOB2 else "1", "episode_label": "Phim kiểm tra · Tập " + ("2" if job_id == JOB2 else "1"), "memory_available": True, "step": 5 if job_id == JOB2 else 2,
                       "preview": [{"id": 1, "start": "00:00:01,000", "end": "00:00:02,000", "text": "Xin chào."}]}
            if job_id == JOB1 and state["hold_status"]:
                state["held"].append((route, payload))
                return
        elif parsed.path == "/api/translation/start":
            state["starts"].append(json.loads(route.request.post_data))
            route.fulfill(status=409, json={"error": "Đang có phiên dịch. Hãy chờ hoàn tất hoặc hủy phiên đang chạy."})
            return
        elif parsed.path == "/api/translation/artifact":
            assert parse_qs(parsed.query)["name"] == ["memory.json"]
            if state["fail"]:
                route.fulfill(status=400, json={"error": "File chưa sẵn sàng."})
                return
            payload = MEMORY if parse_qs(parsed.query)["id"] == [JOB1] else LEGACY
        else:
            unexpected.append(parsed.path)
            route.fulfill(status=404, json={"error": "Unexpected test route"})
            return
        route.fulfill(json=payload)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="msedge", headless=True, args=list(HEADLESS_BROWSER_ARGS))
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("download", lambda download: downloads.append(download.suggested_filename))
        page.route("**/*", route_handler)
        page.goto("http://127.0.0.1:18766/")
        expect(page.locator(".album")).to_have_count(5)
        output = ROOT / ".tmp" / "memory-preview"
        output.mkdir(parents=True, exist_ok=True)
        # Core library actions stay visible; setup and statistics open on demand.
        expect(page.locator("#localizeIqiyiButton")).not_to_be_visible()
        expect(page.locator(".overview")).not_to_be_visible()
        page.screenshot(path=str(output / "library-desktop.png"))
        page.locator("#libraryQuery").fill("truong an")
        expect(page.locator(".album")).to_have_count(1)
        page.locator("#libraryClearSearch").click()
        page.get_by_role("button", name="Thêm phim", exact=True).click()
        expect(page.locator("#movieQuery")).to_be_visible()
        page.get_by_role("button", name="Thêm phim", exact=True).click()
        page.get_by_role("button", name="Cài đặt", exact=True).click()
        expect(page.locator("#appSettings")).to_be_visible()
        page.screenshot(path=str(output / "app-settings.png"))
        page.get_by_role("button", name="Model & provider", exact=True).click()
        expect(page.locator("#appSettings")).not_to_be_visible()
        expect(page.locator("#translationSettings")).to_be_visible()
        page.locator("#providerNew").click()
        expect(page.locator("#providerEditor")).to_be_visible()
        expect(page.locator("#providerEditorCancel")).to_have_text("Hủy thêm")
        expect(page.locator("#providerManualModel, #providerAddModel")).to_have_count(0)
        for left, right in (("providerName", "providerType"), ("providerUrl", "providerKey")):
            a, b = page.locator("#" + left).bounding_box(), page.locator("#" + right).bounding_box()
            assert abs(a["y"] - b["y"]) < 1 and abs(a["height"] - b["height"]) < 1, (a, b)
        page.locator("#translationSettings").evaluate("node => node.scrollTop = node.scrollHeight")
        page.screenshot(path=str(output / "model-settings.png"))
        page.set_viewport_size({"width": 375, "height": 812})
        assert page.locator("#translationSettings").evaluate("node => node.scrollWidth <= node.clientWidth")
        page.locator("#translationSettings").evaluate("node => node.scrollTop = node.scrollHeight")
        page.screenshot(path=str(output / "model-settings-mobile.png"))
        page.set_viewport_size({"width": 1280, "height": 900})
        page.locator("#providerName").fill("Provider kiểm tra")
        page.locator("#providerKey").fill("test-fixture-key")
        page.locator("#providerScanModels").click()
        expect(page.locator("#providerScanStatus")).to_contain_text("Provider không trả model nào")
        assert "thủ công" not in page.locator("#providerScanStatus").inner_text()
        state["models"] = [{"id": "fixture-model", "name": "Model kiểm tra"}]
        page.locator("#providerScanModels").click()
        expect(page.locator("#providerScanStatus")).to_contain_text("Tìm thấy 1 model")
        page.locator("#providerEditor button[type=submit]").click()
        expect(page.locator("#providerEditor")).to_be_hidden()
        page.locator("#providerEdit").click()
        expect(page.locator("#providerEditorCancel")).to_have_text("Hủy sửa")
        page.locator("#providerName").fill("Tên chưa lưu")
        page.locator("#providerEditorCancel").click()
        page.locator("#providerEdit").click()
        expect(page.locator("#providerName")).to_have_value("Provider kiểm tra")
        page.locator("#providerEditorCancel").click()
        page.locator("#providerNew").click()
        expect(page.locator("#providerEditorCancel")).to_have_text("Hủy thêm")
        page.locator("#providerEditorCancel").click()
        expect(page.locator("#providerEditor")).to_be_hidden()
        page.set_viewport_size({"width": 375, "height": 812})
        page.keyboard.press("Escape")
        page.get_by_role("button", name="Cài đặt", exact=True).click()
        assert page.locator("#appSettings").evaluate("node => node.scrollWidth <= node.clientWidth")
        page.get_by_role("button", name="Proxy", exact=True).click()
        expect(page.locator("#iqiyiProxyDialog")).to_be_visible()
        assert page.locator("#iqiyiProxyDialog").evaluate("node => node.scrollWidth <= node.clientWidth")
        page.keyboard.press("Escape")
        page.set_viewport_size({"width": 1280, "height": 900})
        album = page.locator(".album").filter(has=page.get_by_text("Phim kiểm tra", exact=True))
        album.locator(".albumHeading").click()
        colors = album.locator(".episodeChip").evaluate_all("nodes => nodes.map(node => ({bg:getComputedStyle(node).backgroundColor,fg:getComputedStyle(node.querySelector('small')).color}))")
        assert len({row["bg"] for row in colors}) == 6, "Each episode state must have its own background"
        def luminance(css):
            channels = [int(value.strip()) / 255 for value in css.removeprefix("rgb(").removesuffix(")").split(",")]
            return sum(weight * (value / 12.92 if value <= .04045 else ((value + .055) / 1.055) ** 2.4)
                       for weight, value in zip((.2126, .7152, .0722), channels))
        for row in colors:
            assert (luminance(row["fg"]) + .05) / (luminance(row["bg"]) + .05) >= 4.5, row
        menu = album.locator(".episodeActions .menu")
        menu.locator("summary").click()
        expect(menu.get_by_role("button", name="Xem phụ đề gốc", exact=True)).to_be_visible()
        page.keyboard.press("Escape")
        assert not menu.evaluate("node => node.open")
        album.locator("#episode-2").click()
        assert album.locator("#episode-2").evaluate("node => getComputedStyle(node).backgroundColor") == colors[1]["bg"], "Selection must preserve the state color"
        expect(album.get_by_role("button", name="Xem bản dịch", exact=True)).to_be_visible()
        menu = album.locator(".episodeActions .menu")
        menu.locator("summary").click()
        expect(menu.get_by_role("button", name="Tải SRT Việt", exact=True)).to_be_visible()
        expect(menu.get_by_role("button", name="Dịch lại", exact=True)).to_be_visible()
        page.keyboard.press("Escape")
        page.screenshot(path=str(output / "library-episodes.png"))
        album.locator(".episodeLegendHelp > summary").click()
        album.locator(".episodeList").screenshot(path=str(output / "episode-colors.png"))
        album.locator(".episodeLegendHelp > summary").click()
        album.get_by_role("button", name="Xem bản dịch", exact=True).click()
        expect(page.locator("#translationPreview")).to_contain_text("Xin chào.")
        assert page.locator("#translationPreviewBox").evaluate("node => node.open")
        expect(page.locator("#translationSourceDetails, #translationFile, #translationUseFile")).to_have_count(0)
        expect(page.locator("#translationEpisodeLabel")).to_have_text("Phim kiểm tra · Tập 2")
        page.screenshot(path=str(output / "translation-result.png"))
        page.keyboard.press("Escape")
        album.locator(".albumHeading").click()
        page.set_viewport_size({"width": 375, "height": 812})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(output / "library-mobile.png"))
        page.set_viewport_size({"width": 812, "height": 375})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.set_viewport_size({"width": 1280, "height": 900})
        page.get_by_role("button", name="Hồ sơ dịch", exact=True).click()
        dialog = page.locator("#translationMemory")
        expect(dialog).to_be_visible()
        expect(dialog.get_by_text("Giáp → Ất", exact=True)).to_be_visible()
        expect(dialog.get_by_text("Ất → Giáp", exact=True)).to_be_visible()
        expect(dialog.get_by_text("Tự xưng", exact=True).first).to_be_visible()
        expect(dialog.get_by_text("triều đình", exact=True)).to_be_visible()
        page.locator("#translationMemoryEpisode").select_option(JOB2)
        expect(dialog.get_by_text("Hai đồng nghiệp bàn việc.", exact=True)).to_be_visible()
        expect(dialog.get_by_text("Câu 12 gọi đồng nghiệp.", exact=True)).to_be_visible()
        expect(dialog.get_by_text("Thuật ngữ công việc.", exact=True)).to_be_visible()
        page.locator("#translationMemoryEpisode").select_option(JOB1)
        expect(dialog.get_by_text("Giáp → Ất", exact=True)).to_be_visible()
        page.get_by_text("Xem JSON gốc", exact=True).click()
        expect(page.locator("#translationMemoryRaw")).to_contain_text('"pronoun_matrix"')
        page.get_by_text("Xem JSON gốc", exact=True).click()
        page.screenshot(path=str(output / "desktop.png"))
        page.set_viewport_size({"width": 375, "height": 812})
        assert dialog.evaluate("node => node.scrollWidth <= node.clientWidth"), "Dialog must not overflow on mobile"
        page.screenshot(path=str(output / "mobile.png"))
        page.keyboard.press("Escape")
        expect(dialog).not_to_be_visible()
        state["fail"] = True
        page.get_by_role("button", name="Hồ sơ dịch", exact=True).click()
        expect(page.locator("#translationMemoryStatus")).to_have_text("File chưa sẵn sàng.")
        expect(page.locator("#translationMemoryContent")).to_be_empty()
        state["fail"] = False
        page.keyboard.press("Escape")
        page.evaluate("showTranslationJob('" + JOB1 + "')")
        page.locator("#translationViewMemory").click()
        expect(dialog.get_by_text("Giáp → Ất", exact=True)).to_be_visible()
        page.keyboard.press("Escape")
        expect(page.locator("#translationPanel")).to_be_visible()
        # A background translation must not block viewing another episode's result.
        state["job1_stage"] = "translation"
        page.evaluate("showTranslationJob('" + JOB1 + "')")
        expect(page.locator("#translationProgress")).to_be_visible()
        expect(page.locator("#translationEpisodeLabel")).to_have_text("Phim kiểm tra · Tập 1")
        page.keyboard.press("Escape")
        album.locator(".albumHeading").click()
        album.locator("#episode-2").click()
        album.get_by_role("button", name="Xem bản dịch", exact=True).click()
        expect(page.locator("#translationTitle")).to_have_text("Bản dịch")
        expect(page.locator("#translationEpisodeLabel")).to_have_text("Phim kiểm tra · Tập 2")
        expect(page.locator("#translationPreview")).to_contain_text("Xin chào.")
        expect(page.locator("#translationProgress")).to_be_hidden()
        expect(page.locator("#translationCancel")).to_be_hidden()
        page.evaluate("window.downloadTranslation=(id,name)=>{window.downloadedJob={id,name}}")
        page.locator("#translationPanel [data-artifact='translated.srt']").click()
        assert page.evaluate("window.downloadedJob") == {"id": JOB2, "name": "translated.srt"}
        page.locator("#translationViewMemory").click()
        expect(dialog.get_by_text("Hai đồng nghiệp bàn việc.", exact=True)).to_be_visible()
        page.keyboard.press("Escape")
        # Late success and failure responses for the old view cannot replace the new one.
        for fail in (False, True):
            state["hold_status"] = True
            with page.expect_request(lambda request: "/api/translation/status?id=" + JOB1 in request.url):
                page.evaluate("window.delayedJobView=showTranslationJob('" + JOB1 + "'); void 0")
            page.evaluate("true")
            assert len(state["held"]) == 1
            state["hold_status"] = False
            page.evaluate("showTranslationJob('" + JOB2 + "')")
            old_route, old_payload = state["held"].pop()
            old_route.fulfill(status=503 if fail else 200, json={"error": "Lỗi của tập cũ"} if fail else old_payload)
            page.evaluate("window.delayedJobView")
            expect(page.locator("#translationEpisodeLabel")).to_have_text("Phim kiểm tra · Tập 2")
            expect(page.locator("#translationProgress")).to_be_hidden()
            expect(page.locator("#translationPreviewBox")).to_be_visible()
            expect(page.locator("#translationReconnect")).to_be_hidden()
        page.screenshot(path=str(output / "translation-selected-result.png"))
        # Rejected attempts to translate another episode keep that episode selected.
        page.evaluate("openTranslationSettings()")
        provider_id = page.locator("#savedProviderEditor").input_value()
        for role in ("context", "translate"):
            page.locator("#" + role + "Provider").select_option(provider_id)
            page.locator("#" + role + "ModelSelect").select_option("fixture-model")
        page.locator("#translationSaveSettings").click()
        album.locator("#episode-3").click()
        album.get_by_role("button", name="Dịch", exact=True).click()
        expect(page.locator("#translationStatus")).to_contain_text("Đang có phiên dịch")
        expect(page.locator("#translationEpisodeLabel")).to_have_text("Phim kiểm tra · Tập 3")
        expect(page.locator("#translationPreviewBox")).to_be_hidden()
        expect(page.locator("#translationProgress")).to_be_hidden()
        assert state["starts"][-1]["tvid"] == "3"
        # Stored model output is data, never HTML.
        rendered = page.evaluate("translationMemoryMarkup({genre: '<img src=x onerror=alert(1)>', characters:[], pronoun_matrix:{}, glossary:{}, translation_style:'ghi chú'})")
        assert "<img" not in rendered and "&lt;img" in rendered
        assert not errors, errors
        assert not downloads, downloads
        assert not unexpected, unexpected
        browser.close()


if __name__ == "__main__":
    check_saved_job()
    check_browser()
    print("UI checks passed: library search, settings, provider editor, episode menus, current/legacy profiles, errors, mobile layout and no downloads.")
