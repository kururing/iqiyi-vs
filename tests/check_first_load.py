"""Cold page, nested frame and ranking clicks against a real isolated Edge runtime."""
import json
from pathlib import Path
import socket
import sys
import threading
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cdp
from iqiyi_common import HEADLESS_BROWSER_ARGS
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
source = (ROOT / "ext/content.js").read_text(encoding="utf-8")
source = "if (/(^|\\.)iqiyi\\.com$/i.test(location.hostname)) {window.__iqiyiViTokenPending=true;\n" + source + "\n}"
pages = {
    "https://localwebapp.iqiyi.com/index.html": """<meta charset=utf-8>
      <script>window.firstEngine=window.__iqiyiViVersion;window.openRequests=[];
      addEventListener('message',e=>{try{window.openRequests.push(JSON.parse(e.data))}catch{}})</script>
      <iframe src="https://www.iqiyi.com/ranks1PCA/2/0"></iframe>""",
    "https://www.iqiyi.com/ranks1PCA/2/0": """<meta charset=utf-8>
      <script>window.firstEngine=window.__iqiyiViVersion;window.legacyClicks=0</script>
      <nav id=category>总榜</nav>
      <a class=rvi__box href="//www.iqiyi.com/v_test123.html" target=_blank
        onclick="window.legacyClicks++;event.preventDefault()"><span>大梦归离</span></a>
      <iframe src="https://m.iqiyi.com/ranks1PCA/2/0"></iframe>""",
    "https://m.iqiyi.com/ranks1PCA/2/0": """<meta charset=utf-8>
      <script>window.firstEngine=window.__iqiyiViVersion</script><nav id=category>热播榜</nav>""",
}
pages["https://localwebapp.iqiyi.com/ranks1PCA/2/0"] = pages["https://www.iqiyi.com/ranks1PCA/2/0"]

with socket.socket() as probe:
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]

with sync_playwright() as pw:
    browser = pw.chromium.launch(channel="msedge", headless=True, args=[*HEADLESS_BROWSER_ARGS,
        f"--remote-debugging-port={port}",
        "--isolate-origins=https://www.iqiyi.com,https://m.iqiyi.com"])
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(f"http://127.0.0.1:{port}/json/version", timeout=3) as response:
        address = json.load(response)["webSocketDebuggerUrl"]
    session = cdp.EarlyScriptSession(address)
    session.install(source)
    stopped = threading.Event()
    errors = []

    def poll():
        try:
            while not stopped.is_set():
                session.poll()
                stopped.wait(0.01)
        except Exception as error:
            errors.append(error)

    worker = threading.Thread(target=poll, daemon=True)
    worker.start()
    try:
        context = browser.new_context()
        context.route("**/*", lambda route: route.fulfill(content_type="text/html", body=pages[route.request.url])
                      if route.request.url in pages else route.abort())
        page = context.new_page()
        page.goto("https://localwebapp.iqiyi.com/index.html", timeout=15000)
        ranking = page.frame_locator("iframe")
        nested = ranking.frame_locator("iframe")
        expect(ranking.locator("#category")).to_have_text("BXH tổng")
        expect(nested.locator("#category")).to_have_text("Đang hot")
        for frame in page.frames:
            assert frame.evaluate("window.firstEngine === window.__iqiyiViVersion && !!window.firstEngine"), frame.url
        ranking.locator("a.rvi__box span").click(modifiers=["Control"])
        assert page.frames[1].evaluate("window.legacyClicks") == 1
        assert page.evaluate("window.openRequests.length") == 0
        page.frames[1].evaluate("window.external.nativeCall=()=>{}")
        page.frames[1].evaluate("window.legacyClicks=0")
        ranking.locator("a.rvi__box span").click()
        expect(page.locator("iframe")).to_have_count(1)
        page.wait_for_function("window.openRequests.length===1")
        request = page.evaluate("window.openRequests[0]")
        assert request == {"cmd": "play", "context": {
            "context": "https://www.iqiyi.com/v_test123.html", "options": {"prefer": "new"}}}, request
        assert page.frames[1].evaluate("window.legacyClicks") == 0
        page.frames[1].evaluate(source)
        ranking.locator("a.rvi__box span").click()
        page.wait_for_function("window.openRequests.length===2")
        assert page.frames[1].evaluate("window.legacyClicks") == 0
        standalone = context.new_page()
        standalone.goto("https://www.iqiyi.com/ranks1PCA/2/0", timeout=15000)
        standalone.locator("a.rvi__box span").click()
        assert standalone.evaluate("window.legacyClicks") == 1, "Preserve ordinary browser navigation"
        page.evaluate("""window.nativeOpenRequests=[];
          window.QySdk={Launcher:{navigate:(url,options)=>window.nativeOpenRequests.push({url,options})}};
          const frame=document.createElement('iframe');frame.id='nativeRanking';
          frame.src='https://localwebapp.iqiyi.com/ranks1PCA/2/0';document.body.append(frame)""")
        native = page.frame_locator("#nativeRanking")
        expect(native.locator("#category")).to_have_text("BXH tổng")
        native.locator("a.rvi__box span").click()
        assert page.evaluate("window.nativeOpenRequests") == [{
            "url": "https://www.iqiyi.com/v_test123.html", "options": {"prefer": "new"}}]
        assert not errors, errors
        print("PASS: first scripts translated, nested isolated frames initialized, ranking click reaches native parent once.")
    except Exception:
        print("CDP errors:", errors, "sessions:", session.sessions,
              "pending:", {key: value[:2] for key, value in session.pending.items()}, flush=True)
        raise
    finally:
        stopped.set()
        worker.join(5)
        session.close()
        browser.close()
