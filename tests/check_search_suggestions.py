"""Run: .venv/Scripts/python.exe tests/check_search_suggestions.py"""
from pathlib import Path
import sys
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from iqiyi_common import HEADLESS_BROWSER_ARGS
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
source = (ROOT / "ext/content.js").read_text(encoding="utf-8")
search_code = source[source.index("  function searchKey("):source.index("  function setUiAttribute(")]
setup = """var SEARCH_TITLE_ALIASES=new Map(), VERIFIED_TITLE_COPY={};
var SEARCH_IN_FLIGHT=false, REPLAYING_SEARCH=false, IQCOM_METADATA_STOPPED=false, IS_RANKING_PAGE=false;
var SEARCH_SUGGEST_TIMER=null, SEARCH_SUGGEST_VERSION=0, SEARCH_SUGGEST_INPUT=null;
window.__iqiyiViPublicApi=true;
function cjkCount(value){return (String(value).match(/[\\u3400-\\u9fff]/g)||[]).length}
function setUiAttribute(el,name,value){el.setAttribute(name,value)}
window.completedSearches=[];
function requestIqcomMetadata(path){return fetch('/api/'+path).then(r=>r.json()).then(value=>{completedSearches.push(new URLSearchParams(path.split('?')[1]).get('q'));return value})}
"""
events = """
injectCSS();
document.addEventListener('input',suggestVietnameseSearch,true);
document.addEventListener('focusin',suggestVietnameseSearch,true);
document.addEventListener('compositionstart',suggestVietnameseSearch,true);
document.addEventListener('compositionend',suggestVietnameseSearch,true);
document.addEventListener('keydown',handleVietnameseSearch,true);
document.addEventListener('click',handleVietnameseSearch,true);
window.submitted=[];
document.querySelector('.search-button-triggle').addEventListener('click',()=>submitted.push(document.querySelector('input').value));
"""
html = """<meta charset="utf-8"><style>body{background:#101214;color:white;font:15px Arial;margin:40px}
#searchbar{width:500px;margin-left:auto}#searchinput{display:flex;border:1px solid #777;padding:8px}
input{flex:1;min-width:0;background:#191c20;color:white;border:0}button{padding:8px}
#search-auto-suggest{padding:30px;background:#292b2e}</style>
<div id="searchbar"><div id="searchinput"><input type="text" aria-label="Tên phim"><button class="search-button-triggle">Tìm</button></div>
<div id="search-auto-suggest">Lịch sử tìm kiếm</div></div><button id="outside">Ngoài ô tìm kiếm</button>"""
requests, held = [], []
choices = [{"title": "Dữ Tấn Trường An", "query": "与晋长安", "year": "2025"}]


def route_request(route):
    parsed = urlsplit(route.request.url)
    if parsed.path == "/":
        route.fulfill(content_type="text/html", body=html)
        return
    keyword = parse_qs(parsed.query).get("q", [""])[0]
    requests.append(keyword)
    if keyword == "tu khoa cu":
        held.append(route)
        return
    payload = {"query": keyword, "suggestions": choices}
    if keyword == "du tan truong an":
        payload.update(query="与晋长安", title="Dữ Tấn Trường An", suggestions=[])
    route.fulfill(json=payload)


with sync_playwright() as pw:
    browser = pw.chromium.launch(channel="msedge", headless=True, args=list(HEADLESS_BROWSER_ARGS))
    page = browser.new_page(viewport={"width": 1000, "height": 700})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.route("http://search.test/**", route_request)
    page.goto("http://search.test/")
    page.evaluate(setup + search_code + events)
    field = page.get_by_role("textbox", name="Tên phim")
    panel = page.locator("#iqiyi-vi-search-suggestions")
    field.fill("du ")
    field.fill("du tan")
    field.fill("du tan truong an")
    expect(panel.get_by_role("button", name="Dữ Tấn Trường An", exact=True)).to_be_visible()
    assert requests == ["du tan truong an"], requests
    expect(field).to_be_focused()
    expect(field).to_have_value("du tan truong an")
    expect(page.locator("#search-auto-suggest")).to_be_hidden()
    assert page.evaluate("submitted") == [], "Typing must not submit a search"
    # A click inside the input keeps the dropdown open; arrows and Escape work.
    field.click()
    expect(panel).to_be_visible()
    field.press("ArrowDown")
    expect(panel.locator("button")).to_be_focused()
    page.keyboard.press("Escape")
    expect(panel).to_have_count(0)
    expect(field).to_be_focused()
    # Old network responses cannot overwrite the current typed query or reopen a closed panel.
    with page.expect_request("**/api/international-search?q=tu%20khoa%20cu"):
        field.fill("tu khoa cu")
    field.fill("tu khoa moi")
    expect(panel.locator("button")).to_have_text("Dữ Tấn Trường An · 2025")
    assert held
    held.pop().fulfill(json={"query": "tu khoa cu", "suggestions": [{"title": "Kết quả cũ", "query": "旧剧"}]})
    page.wait_for_function("completedSearches.includes('tu khoa cu')")
    expect(panel.locator("button")).to_have_text("Dữ Tấn Trường An · 2025")
    # A suggestion submits the verified Chinese query through the original search button.
    panel.locator("button").click()
    page.wait_for_function("submitted.length===1")
    assert page.evaluate("submitted") == ["与晋长安"]
    expect(panel).to_have_count(0)
    # Vietnamese IME input waits until composition finishes.
    before = len(requests)
    field.focus()
    field.evaluate("el=>{el.value='nhap bang IME';el.dispatchEvent(new CompositionEvent('compositionstart',{bubbles:true}));el.dispatchEvent(new InputEvent('input',{bubbles:true,isComposing:true}))}")
    page.wait_for_timeout(350)
    assert len(requests) == before
    field.dispatch_event("compositionend")
    expect(panel.locator("button")).to_be_visible()
    field.fill("")
    expect(panel).to_have_count(0)
    field.fill("du tan")
    expect(panel.locator("button")).to_be_visible()
    preview = ROOT / ".tmp" / "search-suggestions"
    preview.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(preview / "desktop.png"))
    page.locator("#outside").click()
    expect(panel).to_have_count(0)
    assert not errors, errors
    browser.close()
print("PASS: live suggestions debounce; exact titles display; IME, focus, selection and stale responses work")
