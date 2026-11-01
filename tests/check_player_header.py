"""One native caption in windowed mode, with controls retained in fullscreen/mini/web."""
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from iqiyi_common import HEADLESS_BROWSER_ARGS
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
css = subprocess.check_output([
    'node', '-e', "const fs=require('node:fs'),vm=require('node:vm'),s=fs.readFileSync(process.argv[1],'utf8');"
    "process.stdout.write(vm.runInNewContext(s.slice(s.indexOf('  function playerOverlayCSS()'),s.indexOf('  function managerShortcutCSS()'))+'playerOverlayCSS()'));",
    str(ROOT / 'ext/content.js')], text=True, encoding='utf-8')

with sync_playwright() as pw:
    browser = pw.chromium.launch(channel='msedge', headless=True, args=list(HEADLESS_BROWSER_ARGS))
    try:
        page = browser.new_page(viewport={'width': 1000, 'height': 600})
        page.set_content('''<style>
          body{margin:0;background:#101214;color:#eee;font:16px Arial}
          .XPlayer_root__test{position:relative;width:100%;height:500px}
          #fixed,#overlay{height:48px;background:#27282a;display:flex;align-items:center;justify-content:space-between;padding:0 16px}
          #cover{position:relative;height:450px;background:#080808}
          #overlay{position:absolute;inset:0 0 auto;opacity:1;transform:none}
          .XPlayer_invisible__test,.XPlayer_headerNone__test{display:none!important}
          button{background:#333;color:white;border:0;padding:8px}
          </style><style>''' + css + '''</style>
          <main class="XPlayer_root__test">
            <header id="fixed" class="XPlayer_headTop__test"><span>Ninh An Như Mộng · Tập 13</span><button>Đóng cửa sổ</button></header>
            <div id="cover"><header id="overlay" class="XPlayer_longHead__test"><span>Tiêu đề phủ lên video</span><button>Thoát toàn màn hình</button></header></div>
          </main>''')
        expect(page.locator('#fixed')).to_be_visible()
        expect(page.locator('#fixed button')).to_be_visible()
        expect(page.locator('#overlay')).to_be_hidden()
        page.locator('#cover').hover()
        expect(page.locator('#overlay')).to_be_hidden()
        page.locator('#overlay').evaluate("n=>n.className='XPlayer_longHeadXPlayer2026__test'")
        expect(page.locator('#overlay')).to_be_hidden()
        output = ROOT / '.tmp/player-header'
        output.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(output / 'windowed.png'))

        for hidden_class in ('XPlayer_invisible__test', 'XPlayer_headerNone__test'):
            page.locator('#fixed').evaluate('(n,c)=>n.classList.add(c)', hidden_class)
            expect(page.locator('#overlay')).to_be_visible()
            page.locator('#fixed').evaluate('(n,c)=>n.classList.remove(c)', hidden_class)
            expect(page.locator('#overlay')).to_be_hidden()

        page.evaluate("window.fixedHeader=document.querySelector('#fixed');fixedHeader.remove()")
        expect(page.locator('#overlay')).to_be_visible()
        expect(page.locator('#overlay button')).to_be_visible()
        page.screenshot(path=str(output / 'fullscreen.png'))
        page.locator('main').evaluate("n=>n.classList.add('XPlayer_rootMini__test')")
        expect(page.locator('#overlay')).to_be_visible()
        page.locator('#overlay').evaluate("n=>n.className='XPlayer_webLongHead__test'")
        expect(page.locator('#overlay')).to_be_visible()
        page.evaluate("document.querySelector('main').prepend(fixedHeader)")
        expect(page.locator('#overlay')).to_be_visible()
        page.locator('#overlay').evaluate("n=>n.className='XPlayer_longHead__test'")
        expect(page.locator('#overlay')).to_be_hidden()
        print('PASS: one fixed header, no duplicate on hover; fullscreen, mini, web and late remount keep their controls.')
    finally:
        browser.close()
