r"""Run with: .venv\Scripts\python.exe tests\test_ui_startup.py"""
import json
from pathlib import Path
import socket
import sys
import urllib.request

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import cdp


HTML = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"></head><body>
<div id="btn_gameBtn"><span id="text">游戏大厅</span></div>
<span id="normal">播放</span>
<a href="/a_12345678901234.html"><h2 class="movie-title">逐玉</h2></a>
<div class="caption-main">播放</div><textarea>播放</textarea>
<script>
window.paints = [];
function capture() {
  paints.push([document.querySelector('#btn_gameBtn #text').textContent,
    document.querySelector('#normal').textContent,
    document.querySelector('.movie-title').textContent]);
  requestAnimationFrame(capture);
}
requestAnimationFrame(capture);
</script></body></html>"""


def check_before_paint(page):
    page.wait_for_function("paints.length >= 3")
    assert page.evaluate("paints.every(p => JSON.stringify(p) === JSON.stringify(['Game','Phát','Trục Ngọc']))"), page.evaluate("paints")
    assert page.locator(".caption-main").text_content() == "播放"
    assert page.locator("textarea").input_value() == "播放"
    assert page.evaluate("window.__metadataCalls") == 0, "Prepared titles must not wait for metadata"
    assert page.locator("#iqiyi-vi-css").count() == 1


def main():
    manifest = json.loads((ROOT / "ext/manifest.json").read_text(encoding="utf-8"))
    ui_script = next(item for item in manifest["content_scripts"] if "content.js" in item["js"])
    assert ui_script["run_at"] == "document_start"
    engine = (ROOT / "ui-engine.js").read_text(encoding="utf-8")
    for name in ("lwa-vi.js", "ext/content.js"):
        assert (ROOT / name).read_text(encoding="utf-8") == engine, name
    source = """window.__metadataCalls = 0; window.__iqiyiViToken = 'test';
window.__pendingMetadata = [];
window.fetch = function () { window.__metadataCalls++; return new Promise(function (resolve) {
  window.__pendingMetadata.push(resolve);
}); };
""" + engine
    with socket.socket() as free_port:
        free_port.bind(("127.0.0.1", 0))
        port = free_port.getsockname()[1]
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True,
                                    args=[f"--remote-debugging-port={port}"])
        try:
            page = browser.new_page()
            page.route("https://www.iqiyi.com/**", lambda route: route.fulfill(
                status=200, content_type="text/html; charset=utf-8", body=HTML))
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(f"http://127.0.0.1:{port}/json/list") as response:
                target = next(t for t in json.load(response) if t["type"] == "page")
            session = cdp.ScriptSession(target)
            try:
                session.install([source])
                page.goto("https://www.iqiyi.com/start")
                check_before_paint(page)
                # React reuses text nodes, replaces children, and updates attributes.
                result = page.evaluate("""async () => {
                  const label = document.querySelector('#btn_gameBtn #text');
                  label.firstChild.nodeValue = '游戏大厅';
                  document.querySelector('#normal').firstChild.nodeValue = '暂停';
                  document.querySelector('.caption-main').firstChild.nodeValue = '暂停';
                  await new Promise(requestAnimationFrame);
                  const first = [label.textContent, document.querySelector('#normal').textContent];
                  label.replaceChildren(document.createTextNode('游戏大厅'));
                  label.title = '游戏大厅';
                  await new Promise(requestAnimationFrame);
                  return [first, label.textContent, label.title,
                    document.querySelector('.caption-main').textContent];
                }""")
                assert result == [["Game", "Tạm dừng"], "Game", "Game", "暂停"], result
                # No watcher reinjection between reloads: the persistent session owns init scripts.
                for _ in range(2):
                    page.reload()
                    check_before_paint(page)
                result = page.evaluate("""async () => {
                  const card = document.createElement('a');
                  card.href = '/a_23456789012345.html';
                  card.innerHTML = '<span class="movie-title">未知剧名</span><button>播放</button>';
                  document.body.appendChild(card);
                  await new Promise(requestAnimationFrame);
                  const title = card.querySelector('span');
                  const pending = [getComputedStyle(title).visibility,
                    getComputedStyle(card.querySelector('button')).visibility];
                  // A repeated scan must keep the same pending label masked.
                  window.__iqiyiViReload();
                  await new Promise(requestAnimationFrame);
                  pending.push(getComputedStyle(title).visibility);
                  window.__pendingMetadata.shift()({ok:true, json:() => Promise.resolve({
                    title:'Tên phim Việt', sourceTitle:'未知剧名'
                  })});
                  await new Promise(requestAnimationFrame);
                  return [pending, title.textContent, getComputedStyle(title).visibility];
                }""")
                assert result == [["hidden", "visible", "hidden"], "Tên phim Việt", "visible"], result
                result = page.evaluate("""async () => {
                  const card = document.createElement('a');
                  card.href = '/a_34567890123456.html';
                  card.innerHTML = '<span class="movie-title">缺少译名</span>';
                  document.body.appendChild(card);
                  await new Promise(requestAnimationFrame);
                  window.__pendingMetadata.shift()({ok:false, status:503});
                  await new Promise(requestAnimationFrame);
                  return [card.textContent, getComputedStyle(card.firstChild).visibility];
                }""")
                assert result == ["缺少译名", "visible"], result
                session.install([source])
                session.install([source + "\nwindow.__updatedInit = true;"])
                page.reload()
                check_before_paint(page)
                assert page.evaluate("window.__updatedInit")
                assert len(session.script_ids) == 1, "Replacing a revision must remove its old init script"
            finally:
                session.close()
            # The extension's document_start path also works independently of CDP.
            context = browser.new_context()
            context.add_init_script(script=source)
            extension_page = context.new_page()
            extension_page.route("https://www.iqiyi.com/**", lambda route: route.fulfill(
                status=200, content_type="text/html; charset=utf-8", body=HTML))
            extension_page.goto("https://www.iqiyi.com/extension")
            check_before_paint(extension_page)
            context.close()
            # An unavailable token service must release labels after bootstrap finishes.
            bootstrap_page = browser.new_page()
            bootstrap_page.route("https://www.iqiyi.com/**", lambda route: route.fulfill(
                status=200, content_type="text/html; charset=utf-8", body=HTML))
            bootstrap_page.goto("https://www.iqiyi.com/bootstrap")
            bootstrap_page.evaluate("""document.body.insertAdjacentHTML('beforeend',
              '<a href="/a_45678901234567.html"><span class="movie-title">未翻译</span></a>');
              window.fetch = () => Promise.reject(new Error('offline'));
            """ + (ROOT / "ext/iqcom-bootstrap.js").read_text(encoding="utf-8") + "\n" + engine)
            bootstrap_page.wait_for_function("window.__iqiyiViTokenPending === false")
            assert bootstrap_page.locator("[data-iqiyi-vi-pending]").count() == 0
            # Some document_start contexts do not have an HTML root yet.
            empty_page = browser.new_page()
            empty_page.evaluate("document.documentElement.remove()")
            empty_page.evaluate(engine)
            result = empty_page.evaluate("""async () => {
              const html = document.createElement('html');
              document.appendChild(html);
              html.innerHTML = '<head></head><body><span>播放</span></body>';
              await new Promise(requestAnimationFrame);
              return [document.querySelector('span').textContent,
                !!document.getElementById('iqiyi-vi-css')];
            }""")
            assert result == ["Phát", True], result
        finally:
            browser.close()
    print("PASS: Vietnamese before paint, React updates, subtitle isolation, persistent navigation, extension startup")


if __name__ == "__main__":
    main()
