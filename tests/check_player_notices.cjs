/* Run: node tests/check_player_notices.cjs */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname,'../ext/content.js'),'utf8');
const context = vm.createContext({IS_RANKING_PAGE:false, TEXT_CACHE:new Map(), MACHINE_COPY:new Map(),
  machineTextKey:s=>s.replace(/\s+/g,' ').trim()});
vm.runInContext(source.slice(source.indexOf('  var FIXED_COPY ='),source.indexOf('  function pumpIqcomMetadata(')) +
  source.slice(source.indexOf('  function trPatterns('),source.indexOf('  function searchKey(')),context);
const chinese = /[\u3400-\u9fff]/;
const screenshot = '高清1080P试看中，黄金/白金/星钻尊享';
assert.equal(context.tr(screenshot),'Đang xem thử 1080P · VIP Vàng/Bạch Kim/Kim Cương');
for(const quality of ['高清1080P','高清 1080P','超清720P','超高清4K','蓝光1080P','HDR']) {
  for(const suffix of ['试看中，黄金/白金/星钻尊享','试用中，白金VIP专享','试看中']) {
    const raw=quality+suffix;
    assert.ok(!chinese.test(context.tr(raw)),raw);
  }
}
for(const raw of [screenshot+'！','已为您自动切换至 超高清4K 画质，限时免费体验，请稍候...',
  '已为您设为 蓝光1080P','已为您设为高清1080P画质','高清1080P画质开启失败，请重试',
  '已切换至高清1080P','正在切换至超高清4K画质','黄金会员，仅剩 3 天','5秒后可跳过此广告','3s后可跳过当前广告',
  '尊敬的星钻会员，您正在开启菁彩声','尊敬的黄金会员，已为您跳过30秒广告',
  '已切换主字幕为简体中文','已关闭副字幕','上次观看至 12:34 处，已为您自动续播']) {
  assert.ok(!chinese.test(context.tr(raw)),raw+' => '+context.tr(raw));
}
const fixed = Object.keys(context.FIXED_COPY).filter(raw => /试看|试用|失败|错误|已为您|正在|无法|已切换|网络|超时|已开启|已关闭|画质|跳过|音效|解码器/.test(raw));
for(const raw of fixed) assert.ok(!chinese.test(context.tr(raw)),raw);
assert.equal(context.tr('萌宝上门清冷爹变奶爸'),'萌宝上门清冷爹变奶爸','Notification rules must not guess film names');
console.log(`Player notice checks passed: screenshot, 18 quality/trial variants, dynamic notices and ${fixed.length} prepared messages without a network request.`);
