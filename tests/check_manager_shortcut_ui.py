"""The back-to-top control stays above the manager, with its full Vietnamese label."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from iqiyi_common import HEADLESS_BROWSER_ARGS
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
source = (ROOT / "ext/content.js").read_text(encoding="utf-8")
css = source[source.index("  function playerOverlayCSS()"):source.index("  function setUiAttribute(")]
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
    # The web button asks the extension to open the native window without a new tab.
    page.route("https://www.iqiyi.com/**", lambda route: route.fulfill(content_type="text/html", body=html))
    page.goto("https://www.iqiyi.com/")
    page.evaluate("""window.managerRequests=[];window.__iqiyiViToken='fixture-player-token';
        window.__iqiyiViLocalFetch=async (url,options)=>{
            managerRequests.push({url,method:options.method});
            return new Response('{"ok":true}',{status:200});
        };void 0;""")
    page.evaluate("var IS_RANKING_PAGE=false;" + css + shortcut + "injectCSS();installManagerShortcut();")
    tabs_before = len(page.context.pages)
    page.locator("#iqiyi-vi-manager").click()
    expect(page.locator("#iqiyi-vi-manager")).to_have_attribute("title", "Đã mở quản lý phụ đề")
    assert page.evaluate("managerRequests") == [{"url": "http://127.0.0.1:18766/api/open-manager", "method": "POST"}]
    assert len(page.context.pages) == tabs_before
    # Load the complete content script at document_start, as the real extension does.
    # The web toolbar is absent at DOMContentLoaded, then mounts and gets hydrated.
    lifecycle = browser.new_page(viewport={"width": 1280, "height": 800})
    lifecycle.route("https://www.iqiyi.com/**", lambda route: route.fulfill(
        content_type="text/html", body="<meta charset=utf-8><body></body>"))
    lifecycle.add_init_script(source)
    lifecycle.goto("https://www.iqiyi.com/")
    expect(lifecycle.locator("#iqiyi-vi-manager")).to_have_count(0)
    lifecycle.evaluate("html=>document.body.innerHTML=html", html)
    expect(lifecycle.locator("#iqiyi-vi-manager")).to_be_visible()
    lifecycle.locator("#iqiyi-vi-manager").evaluate("n=>n.remove()")
    expect(lifecycle.locator("#iqiyi-vi-manager")).to_be_visible()
    lifecycle.evaluate("html=>document.body.innerHTML=html", html)
    expect(lifecycle.locator("#iqiyi-vi-manager")).to_be_visible()
    lifecycle.evaluate(source)
    expect(lifecycle.locator("#iqiyi-vi-manager")).to_have_count(1)
    # The retained shortcut works without translating native labels, including after navigation.
    lifecycle.add_init_script("window.__iqiyiViManagerOnly=true;")
    lifecycle.goto("https://www.iqiyi.com/")
    lifecycle.evaluate("window.__iqiyiViManagerOnly=true;" + source)
    lifecycle.evaluate("html=>document.body.innerHTML=html+'<p id=original>我的资产</p>'", html)
    expect(lifecycle.locator("#iqiyi-vi-manager")).to_be_visible()
    expect(lifecycle.locator("#original")).to_have_text("我的资产")
    lifecycle.evaluate("""window.__iqiyiViToken='fixture-player-token';
      window.__iqiyiViLocalFetch=async()=>new Response('{"ok":true}',{status:200});""")
    lifecycle.locator("#iqiyi-vi-manager").click()
    expect(lifecycle.locator("#iqiyi-vi-manager")).to_have_attribute("title", "Đã mở quản lý phụ đề")
    lifecycle.locator("#iqiyi-vi-manager").evaluate("n=>n.remove()")
    expect(lifecycle.locator("#iqiyi-vi-manager")).to_be_visible()
    lifecycle.evaluate("window.__iqiyiViManagerOnly=false;" + source)
    expect(lifecycle.locator("#original")).to_have_text("Tài sản của tôi")
    expect(lifecycle.locator("#iqiyi-vi-manager")).to_have_count(1)
    retained = browser.new_page()
    retained.add_init_script("window.__iqiyiViManagerOnly=true;" + source)
    retained.route("https://localwebapp.iqiyi.com/**", lambda route: route.fulfill(
        content_type="text/html", body=html + '<p id="original">我的资产</p>'))
    for url in ("https://localwebapp.iqiyi.com/", "https://localwebapp.iqiyi.com/index.html"):
        retained.goto(url)
        expect(retained.locator("#iqiyi-vi-manager")).to_be_visible()
        expect(retained.locator("#original")).to_have_text("我的资产")
    player_html = """<meta charset=utf-8><style>
      body{margin:0;background:#101214;color:white;font:14px Arial}
      .configPage_configPage__test{position:absolute;right:0;top:50px;bottom:0;width:340px;background:#222}
      .configPage_bottomRightFloatingWidget__test{position:absolute;right:16px;bottom:16px;display:flex;flex-direction:column;align-items:flex-end;width:38px}
      .backTop_iconBtn__test,.configPage_feedbackBtn__test{height:38px;width:38px;background:#333;border-radius:8px}
      .backTop_iconBtn__test{margin-bottom:12px}
      .configPage_backTop__test{display:flex;flex-direction:row-reverse;align-items:center;width:36px;height:36px;margin-bottom:12px;background:#333;border:1px solid #444;border-radius:8px;transition:width .1s;cursor:pointer}
      .configPage_backTop__test>[id=icon]{width:20px;height:20px;margin:8px;flex-shrink:0}
      .configPage_backTop__test>[id=text]{width:0;overflow:hidden;white-space:nowrap;font-size:14px}
      .configPage_backTop__test:hover{width:104px}
      .configPage_backTop__test:hover>[id=text]{width:56px;margin:10px -2px 10px 12px}
      </style><aside class=configPage_configPage__test><div class=configPage_bottomRightFloatingWidget__test>
      <div class=backTop_iconBtn__test>Xu</div><div class=configPage_feedbackBtn__test>?</div></div></aside>"""
    player = browser.new_page(viewport={"width":1920,"height":1040})
    player.route("https://localwebapp.iqiyi.com/**", lambda route: route.fulfill(content_type="text/html",body=player_html))
    player.add_init_script(source)
    player.goto("https://localwebapp.iqiyi.com/player.html")
    manager = player.locator("#iqiyi-vi-manager")
    expect(manager).to_be_visible()
    # The native back-to-top control is mounted later, when the sidebar scrolls.
    player.evaluate("""const top=document.createElement('div');top.className='configPage_backTop__test';
      top.innerHTML='<div id=icon>↑</div><span id=text>Về đầu trang</span>';document.querySelector('.configPage_bottomRightFloatingWidget__test').append(top);""")
    for width,height in ((1920,1040),(1000,700),(375,812)):
        player.set_viewport_size({"width":width,"height":height})
        expect(manager).to_be_visible()
        expect(manager).to_have_count(1)
        a,b=manager.bounding_box(),player.locator('.backTop_iconBtn__test').bounding_box()
        top_box=player.locator('.configPage_backTop__test').bounding_box()
        assert top_box['y']+top_box['height']<=a['y']
        assert a['y']+a['height']<=b['y'] and a['x']==b['x']
        assert a['x']>=0 and a['x']+a['width']<=width
        back_top=player.locator('.configPage_backTop__test')
        back_top.hover()
        player.wait_for_timeout(150)
        assert back_top.locator('[id=text]').evaluate('e=>e.scrollWidth<=e.clientWidth+1'), 'The Vietnamese back-to-top label must not be clipped'
        top_box=back_top.bounding_box()
        assert top_box['x']>=0 and top_box['x']+top_box['width']<=width
        player.screenshot(path=str(output/f"player-tools-{width}.png"))
        player.mouse.move(0,0)
    player.evaluate("""window.managerRequests=[];window.__iqiyiViToken='fixture-player-token';
      window.__iqiyiViLocalFetch=async(url,options)=>{managerRequests.push({url,method:options.method});return new Response('{"ok":true}',{status:200})};void 0;""")
    manager.focus()
    player.keyboard.press('Enter')
    expect(manager).to_have_attribute('title','Đã mở quản lý phụ đề')
    assert player.evaluate('managerRequests')==[{"url":"http://127.0.0.1:18766/api/open-manager","method":"POST"}]
    player.evaluate("html=>document.body.innerHTML=html",player_html)
    expect(manager).to_be_visible()
    expect(manager).to_have_count(1)
    player.evaluate(source)
    expect(manager).to_have_count(1)
    browser.close()
print("PASS: back-to-top order, label fits, webapp opens, late-mounted/hydrated toolbar restores exactly one shortcut")
