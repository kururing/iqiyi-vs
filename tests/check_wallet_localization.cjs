/* Run: node tests/check_wallet_localization.cjs */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../ext/content.js'), 'utf8');
const context = vm.createContext({IS_RANKING_PAGE:false, TEXT_CACHE:new Map(), MACHINE_COPY:new Map(),
  machineTextKey:s=>s.replace(/\s+/g,' ').trim()});
vm.runInContext(source.slice(source.indexOf('  var FIXED_COPY ='), source.indexOf('  function pumpIqcomMetadata(')) +
  source.slice(source.indexOf('  function trPatterns('), source.indexOf('  function searchKey(')) +
  source.slice(source.indexOf('  function localizeWalletPromotions('), source.indexOf('  function localizeFixedUI(')), context);
for (const raw of ['我的资产','零钱','奇点','优惠券','银行卡','零钱明细','安全设置','福利优选','更多福利',
  '人人都可领会员','最高免费得63天会员','移动积分免费兑会员','积分不用白不用 速来','月月免费领VIP月卡',
  '移动用户专享  加送流量','首次借款送1个月VIP','新人福利 达标即送','手机爱奇艺APP扫码领福利']) {
  assert.doesNotMatch(context.tr(raw), /[\u3400-\u9fff]/, raw);
}
const ids = ['b2c675690a6bf6a54357985448180812', '471df0fbaaad55ea90023fdca65a7e76',
  '34916161be1a6c52a63fb61edf950017', '1b93db390e48440b5ebdbe463f6f543d', '0e8ec0d6edaf31c78cfa7a3f6fb5b3b4'];
const images = [...ids, 'unknown-campaign'].map(id => {
  const attrs = new Map([['src', 'https://static-d.iqiyi.com/rms/' + id + '.png']]);
  return {getAttribute:key=>attrs.get(key) || null, setAttribute:(key,value)=>attrs.set(key,value),
    clickBinding:()=>id};
});
context.queryFixed = scope => scope || images;
context.setUiAttribute = (img, key, value) => img.setAttribute(key, value);
context.localizeWalletPromotions();
const firstSources = images.map(img => img.getAttribute('src'));
images.slice(0,5).forEach((img,index) => {
  const svg = decodeURIComponent(img.getAttribute('src').split(',')[1]);
  assert.match(svg, /<svg /);
  assert.match(svg, /VIP/);
  assert.doesNotMatch(svg, /[\u3400-\u9fff]/);
  assert.equal(img.getAttribute('data-iqiyi-vi-offer-id'), ids[index]);
  assert.ok(img.getAttribute('alt'));
  assert.equal(img.clickBinding(), ids[index], 'Keep the existing campaign action');
  fs.mkdirSync(require('node:path').join(__dirname, '../.tmp/wallet-preview'), {recursive:true});
  fs.writeFileSync(require('node:path').join(__dirname, '../.tmp/wallet-preview', index + '.svg'), svg);
});
context.localizeWalletPromotions();
assert.deepEqual(images.map(img=>img.getAttribute('src')), firstSources, 'Repeated passes are stable');
assert.match(images[5].getAttribute('src'), /unknown-campaign.png$/, 'Do not invent copy for unknown campaigns');
images[0].setAttribute('src', 'https://static-d.iqiyi.com/rms/' + ids[2] + '.png');
context.localizeWalletPromotions([images[0]]);
assert.equal(images[0].getAttribute('data-iqiyi-vi-offer-id'), ids[2], 'Recycled images follow the new offer');
images[0].setAttribute('src', 'https://static-d.iqiyi.com/rms/future-offer.png');
context.localizeWalletPromotions([images[0]]);
assert.match(images[0].getAttribute('src'), /future-offer.png$/, 'A new campaign must not inherit stale wording');
console.log('Wallet checks passed: offline labels, five campaign assets, stable repeats, reused images and unknown campaigns.');
