/* Generate browser regression fixture: node tests/check_wallet_layout.cjs
   Serve .tmp, open wallet-layout.html, and check that all rows say PASS. */
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../ext/content.js'), 'utf8');
let css = '';
const context = vm.createContext({IS_RANKING_PAGE:false, document:{documentElement:{},
  getElementById:()=>null, createElement:()=>({}), head:{appendChild:el=>{css=el.textContent;}}}});
vm.runInContext(source.slice(source.indexOf('  function injectCSS('), source.indexOf('  function setUiAttribute(')), context);
context.injectCSS();
const labels = ['Ai cũng có thể nhận VIP', 'Đổi điểm China Mobile lấy VIP',
  'Nhận thẻ VIP tháng miễn phí mỗi tháng', 'Vay lần đầu, tặng 1 tháng VIP'];
const details = ['Nhận miễn phí tối đa 63 ngày VIP', 'Dùng điểm đổi quà ngay',
  'Dành cho thuê bao China Mobile, tặng thêm data', 'Ưu đãi khách mới khi đủ điều kiện'];
const vendor = `.pcw-box-welfare{display:flex;justify-content:space-between}
.pcw-box-welfare .welfare-banner{flex:1;max-width:23.11%;padding:1.7vw;margin-right:12px;background:#1c1d1f;border-radius:12px}
.pcw-box-welfare .welfare-banner:last-child{margin-right:0}
.banner-tip1{font-size:22px;margin-bottom:16px}.banner-tip2{font-size:18px;color:#aaa;margin-bottom:24px}
.banner-image{width:100%;border-radius:12px}`;
const rows = [1284,900,560,260].map(width=>`<section style="width:${width}px;max-width:100%" data-width="${width}">
<h2>${width}px</h2><div class="pcw-wrap"><div class="pcw-box-welfare">${labels.map((label,index)=>
  `<div class="welfare-banner"><div class="banner-content"><div class="banner-tip1">${label}</div>
  <div class="banner-tip2">${details[index]}</div></div><img class="banner-image" src="wallet-preview/${index+1}.svg"></div>`).join('')}
</div></div></section>`).join('');
const check = `
window.addEventListener('load',()=>{
  const results=[...document.querySelectorAll('section')].map(section=>{
    const grid=section.querySelector('.pcw-box-welfare'), gridRect=grid.getBoundingClientRect();
    const cards=[...grid.children], expectedColumns=Math.max(1,Math.floor((gridRect.width+16)/276));
    const expectedWidth=(gridRect.width-(expectedColumns-1)*16)/expectedColumns;
    const widths=cards.map(card=>card.getBoundingClientRect().width);
    const pass=cards.every(card=>{
      const rect=card.getBoundingClientRect();
      return Math.abs(rect.width-expectedWidth)<2 && rect.height<650 &&
        card.scrollWidth<=card.clientWidth+1 && rect.right<=gridRect.right+1;
    });
    return {width:section.dataset.width,pass,expectedWidth,widths};
  });
  document.getElementById('results').textContent=results.map(row=>row.width+'px: '+(row.pass?'PASS':'FAIL')).join(' · ');
  document.title=results.every(row=>row.pass)?'PASS · Wallet layout':'FAIL · Wallet layout';
});`;
const html = `<!doctype html><html lang="vi"><meta charset="utf-8"><title>Wallet layout</title>
<style>body{background:#14161a;color:#fff;font-family:Arial;margin:24px}section{margin-bottom:40px}h2{font-size:18px}pre{white-space:pre-wrap}${css}</style>
<!-- Load vendor CSS afterwards, like the live iframe. -->
<style>${vendor}</style><h1>Kiểm tra thẻ ưu đãi</h1><pre id="results">Loading…</pre>${rows}<script>${check}</script></html>`;
fs.mkdirSync(path.join(__dirname,'../.tmp'),{recursive:true});
fs.writeFileSync(path.join(__dirname,'../.tmp/wallet-layout.html'),html);
console.log('Generated .tmp/wallet-layout.html from the shared CSS with the original percentage limit and margins.');
