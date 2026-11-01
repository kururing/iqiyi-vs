"""VIP account card: Vietnamese copy, aligned rows, dynamic points and campaign badges."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from iqiyi_common import HEADLESS_BROWSER_ARGS
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
source = (ROOT / "ext/content.js").read_text(encoding="utf-8")
icon = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='44' height='44'%3E%3Crect x='8' y='8' width='28' height='28' rx='8' fill='none' stroke='%23ffc6b3' stroke-width='3'/%3E%3C/svg%3E"
vendor_css = """
*{box-sizing:border-box}body{margin:20px;background:#151515;color:#fff;font:14px Arial}
.fixture{max-width:100%;width:564px}
.bannerV2_userCard__f{position:relative;display:flex;flex-direction:column;width:564px;height:316px;border:1px solid #66594c;border-radius:16px;background:linear-gradient(130deg,#4b3d30,#252525)}
.bannerV2_row1__f{display:flex;justify-content:space-between;padding:42px 32px 0 28px;font-size:20px}
.bannerV2_userName__f{display:flex;min-width:0;max-width:100%;width:100%;font-size:24px;line-height:24px;font-weight:bold;margin-bottom:16px}
.bannerV2_name__f{flex:0 1 auto;min-width:0;white-space:nowrap}
.bannerV2_expireInfo__f{position:relative;display:flex;align-items:center;line-height:18px;font-size:18px;margin-bottom:20px}
.bannerV2_renewButton__f{position:relative;display:flex;align-items:center;justify-content:center;width:190px;height:48px;border-radius:24px;color:#141414;background:#ffd2bd;cursor:pointer}
.bannerV2_VipMarketingBadge__f{position:absolute;right:0;bottom:40px;height:22px;line-height:22px;font-size:14px;padding:0 8px;border-radius:4px;background:#ff6247;color:#fff}
.bannerV2_levelLogo__f{position:absolute;right:8px;top:18px;width:205px;height:180px;object-fit:contain}
.bannerV2_row2__f{display:flex;justify-content:space-between;margin-top:32px;padding:0 28px}
.bannerV2_pointsInfo__f{display:flex;flex-direction:column;align-items:center;justify-content:space-between;cursor:pointer}
.bannerV2_row2_1__f{margin:2px 0 14px}
.bannerV2_pointsAmount__f{display:inline-block;color:#ffc6b3;font-size:40px;line-height:40px}
.bannerV2_pointsLabel__f{color:#ffc6b3;font-size:20px;line-height:20px;margin-left:4px}
.bannerV2_row2Text__f{font-size:18px;line-height:18px;text-align:center;color:#fff3e5}
.bannerV2_privilegeItem__f{display:flex;flex-direction:column;align-items:center;cursor:pointer}
.bannerV2_privilegeIcon__f{width:44px;height:44px;margin-bottom:12px}
@media(max-width:1700px){.fixture,.bannerV2_userCard__f{width:508px}.bannerV2_userCard__f{height:285px}}
@media(max-width:1360px){.fixture,.bannerV2_userCard__f{width:428px}.bannerV2_userCard__f{height:240px}.bannerV2_row1__f{padding:32px 25px 0 21px}.bannerV2_row2Text__f{font-size:14px;line-height:14px}}
"""
html = f"""<!doctype html><html lang="vi"><meta charset="utf-8"><title>VIP card fixture</title>
<div class="fixture"><div class="bannerV2_userCard__f bannerV2_platinum__f">
<div class="bannerV2_row1__f"><div><div class="bannerV2_expireWrap__f">
<div class="bannerV2_userName__f"><span class="bannerV2_name__f">Tài khoản mẫu</span></div>
<div class="bannerV2_expireInfo__f"><div>Hiện đã có các lợi ích bạch kim</div></div></div>
<div class="bannerV2_renewButton__f"><span>Cuộc mua sắm đôi 11</span><div class="bannerV2_VipMarketingBadge__f">Còn 5.1/10 giá gốc</div></div></div>
<img class="bannerV2_levelLogo__f" src="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='205' height='180'%3E%3Ctext x='20' y='115' font-family='Arial' font-size='100' fill='%23ffbc9c'%3EV1%3C/text%3E%3C/svg%3E"></div>
<div class="bannerV2_row2__f"><div class="bannerV2_pointsInfo__f"><div class="bannerV2_row2_1__f"><span class="bannerV2_pointsAmount__f">111</span><span class="bannerV2_pointsLabel__f">tích phân</span></div><div class="bannerV2_row2Text__f">Hệ số điểm 100%</div></div>
{''.join(f'<div class="bannerV2_privilegeItem__f"><img class="bannerV2_privilegeIcon__f" src="{icon}"><span class="bannerV2_row2Text__f">{text}</span></div>' for text in ['Đặc quyền thành viên','Quyền lợi theo hạng','Tài sản của tôi'])}
</div></div></div></html>"""

with sync_playwright() as pw:
    browser = pw.chromium.launch(channel="msedge", headless=True, args=list(HEADLESS_BROWSER_ARGS))
    try:
        page = browser.new_page(viewport={"width": 1920, "height": 900})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route("**/*", lambda r: r.fulfill(content_type="text/html", body=html)
                   if r.request.url == "https://localwebapp.iqiyi.com/vip-card-test" else r.fulfill(status=403, json={}))
        page.goto("https://localwebapp.iqiyi.com/vip-card-test")
        page.evaluate("""window.cardClicks=0;window.originalPoints=document.querySelector('.bannerV2_pointsLabel__f').firstChild;
          for(const node of document.querySelectorAll('.bannerV2_pointsInfo__f,.bannerV2_privilegeItem__f,.bannerV2_renewButton__f'))node.addEventListener('click',()=>cardClicks++);""")
        page.add_script_tag(content=source)
        # The real app can load vendor styles after the localization engine.
        page.add_style_tag(content=vendor_css)
        page.evaluate("__iqiyiViReload()")
        expect(page.locator(".bannerV2_pointsLabel__f")).to_have_text("điểm")
        expect(page.locator(".bannerV2_pointsInfo__f .bannerV2_row2Text__f")).to_have_text("Hệ số: 100%")
        expect(page.locator(".bannerV2_privilegeItem__f").first).to_contain_text("Quyền lợi VIP")
        expect(page.locator(".bannerV2_renewButton__f>span")).to_have_text("Ưu đãi 11.11")
        assert page.evaluate("originalPoints===document.querySelector('.bannerV2_pointsLabel__f').firstChild")
        out = ROOT / ".tmp/vip-layout"
        out.mkdir(parents=True, exist_ok=True)
        for width in (1920, 1600, 1200, 375):
            page.set_viewport_size({"width": width, "height": 900})
            page.wait_for_timeout(40)
            for value in ("111", "123456"):
                page.locator(".bannerV2_pointsAmount__f").evaluate("(el,value)=>el.firstChild.nodeValue=value", value)
                page.wait_for_timeout(40)
                measures = page.evaluate("""()=>{
                  const card=document.querySelector('.bannerV2_userCard__f'),row=document.querySelector('.bannerV2_row2__f');
                  const labels=[...row.querySelectorAll('.bannerV2_row2Text__f')].map(el=>el.getBoundingClientRect());
                  const items=[...row.children],inside=items.every(el=>{const r=el.getBoundingClientRect();return r.left>=card.getBoundingClientRect().left&&r.right<=card.getBoundingClientRect().right&&el.scrollWidth<=el.clientWidth+1});
                  const badge=document.querySelector('.bannerV2_VipMarketingBadge__f').getBoundingClientRect(),button=document.querySelector('.bannerV2_renewButton__f').getBoundingClientRect(),buttonText=document.querySelector('.bannerV2_renewButton__f>span').getBoundingClientRect(),expire=document.querySelector('.bannerV2_expireInfo__f').getBoundingClientRect();
                  return{inside,aligned:innerWidth<=600||labels.every(r=>Math.abs(r.top-labels[0].top)<1),badgeClear:badge.top>=expire.bottom&&badge.bottom<=buttonText.top&&badge.left>=button.left&&badge.right<=button.right,cardContainsRow:row.getBoundingClientRect().bottom<=card.getBoundingClientRect().bottom,noPageOverflow:document.documentElement.scrollWidth<=innerWidth};
                }""")
                assert all(measures.values()), (width, value, measures)
            page.locator(".bannerV2_pointsAmount__f").evaluate("el=>el.firstChild.nodeValue='111'")
            page.wait_for_timeout(40)
            page.locator(".bannerV2_userCard__f").screenshot(path=str(out / f"card-{width}.png"))
        # React can replace the values later; restore labels without replacing its nodes or click handlers.
        page.locator(".bannerV2_pointsLabel__f").evaluate("el=>el.firstChild.nodeValue='积分'")
        page.locator(".bannerV2_pointsInfo__f .bannerV2_row2Text__f").evaluate("el=>el.firstChild.nodeValue='积分系数150%'")
        expect(page.locator(".bannerV2_pointsLabel__f")).to_have_text("điểm")
        expect(page.locator(".bannerV2_pointsInfo__f .bannerV2_row2Text__f")).to_have_text("Hệ số: 150%")
        page.locator(".bannerV2_pointsInfo__f").click()
        page.locator(".bannerV2_privilegeItem__f").first.click()
        page.locator(".bannerV2_renewButton__f").click()
        assert page.evaluate("cardClicks") == 3
        assert not errors, errors
    finally:
        browser.close()
print("PASS: VIP card alignment, badge separation, 4 sizes, long points, dynamic updates and original actions")
