"""The back-to-top control stays above the manager, with its full Vietnamese label."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from iqiyi_common import HEADLESS_BROWSER_ARGS
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
source = (ROOT / "ext/content.js").read_text(encoding="utf-8")
css = source[source.index("  function injectCSS()"):source.index("  function setUiAttribute(")]
shortcut = source[source.index("  function installManagerShortcut()"):source.index("  function run()")]
html = """<meta charset="utf-8"><style>
body{margin:0;min-height:2000px;background:#101214;color:white;font:14px Arial}
.backTop_sideTools__test{position:fixed;right:20px;bottom:20px;display:flex;flex-direction:column;align-items:flex-end;width:38px}
.backTop_sideTools__test>div{position:relative;display:flex;align-items:center;justify-content:center;width:36px;height:36px;border:1px solid #444;border-radius:8px;background:#292c33;margin-bottom:12px;cursor:pointer}
.backTop_backtopNew__test>span{width:0;overflow:hidden;white-space:nowrap}
.backTop_backtopNew__test>div{width:20px;flex-shrink:0}
.backTop_backtopNew__test:hover{width:104px}
.backTop_backtopNew__test:hover>span{width:66px}
</style><div class="backTop_sideTools__test">
<div class="backTop_backtopNew__test" onclick="window.topClicks++;window.scrollTo(0,0)"><span>Về đầu trang</span><div>⌃</div></div>
<div class="backTop_iconBtn__test">Xu</div><div class="backTop_refreshBtn__test">↻</div>
<div class="backTop_feedbackNew__test">?</div></div><script>window.topClicks=0</script>"""

with sync_playwright() as pw:
    browser = pw.chromium.launch(channel="msedge", headless=True, args=list(HEADLESS_BROWSER_ARGS))
    page = browser.new_page(viewport={"width": 1280, "height": 800})
    page.route("https://localwebapp.iqiyi.com/**", lambda route: route.fulfill(content_type="text/html", body=html))
    page.goto("https://localwebapp.iqiyi.com/index.html")
    page.evaluate("var IS_RANKING_PAGE=false;" + css + shortcut + "injectCSS();installManagerShortcut();")
    # DOM reinsertion must never move the custom button above back-to-top visually.
    page.evaluate("document.querySelector('[class*=backTop_sideTools__]').prepend(document.getElementById('iqiyi-vi-manager'))")
    top = page.locator("[class*=backTop_backtopNew__]")
    manager = page.locator("#iqiyi-vi-manager")
    for width, height in ((1280, 800), (375, 812)):
        page.set_viewport_size({"width": width, "height": height})
        top.hover()
        label = top.locator("span")
        assert label.evaluate("n=>n.scrollWidth<=n.clientWidth"), "Vietnamese back-to-top label is clipped"
        a, b = top.bounding_box(), manager.bounding_box()
        assert a["y"] + a["height"] <= b["y"], (a, b)
        assert a["x"] >= 0 and a["x"] + a["width"] <= width
        assert manager.locator("svg").is_visible()
        output = ROOT / ".tmp" / "sidebar-tools"
        output.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(output / f"tools-{width}.png"))
    page.evaluate("window.scrollTo(0,600)")
    top.click()
    page.wait_for_function("scrollY===0&&topClicks===1")
    expect(manager).to_be_visible()
    browser.close()
print("PASS: back-to-top stays first, its label fits, manager stays below, and scrolling still works")
