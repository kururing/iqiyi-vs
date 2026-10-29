/* Run: node tests/check_badge_localization.cjs */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../ext/content.js'), 'utf8');
const freeId = '6b011312d2c447ea90ed9bb47f751db5';
const oldFreeId = '5a2c3f02c5b54771b1047a27cc1f0447';
const vipId = 'c4de74820c254b39ae0d692eef59f3a8';
const theatreId = 'a2556f7166b541be8ad0e24c4db93cbc';
const shortDramaId = '0487461a373d497cae2d159f0b5ddcee';
function image(id, episode = true) {
  const attrs = new Map([['src', 'https://static-s.iqiyi.com/lequ/' + id + '.svg']]);
  return {nodeType: 1, className: episode ? 'marks_mark__hrsdg episodesNew_episodeItemMark__LhIUx' : 'meta_tagIconImage__KVoiP',
    get alt() {return attrs.get('alt') || ''},
    getAttribute: key => attrs.get(key) ?? null,
    setAttribute: (key, value) => attrs.set(key, value),
    style: {setProperty(key, value) {this[key] = value}}, closest: () => null,
    matches(selector) {
      return selector.split(',').some(part => {
        if (!part.startsWith('img[')) return false;
        if (part.includes(':not([data-iqiyi-vi-badge-id])')) return attrs.get('data-iqiyi-vi-fixed') === '1' && !attrs.has('data-iqiyi-vi-badge-id');
        const match = part.match(/^img\[([\w-]+)(\*?)="([^"]+)"\]/);
        if (!match) return false;
        const value = attrs.get(match[1]) || '';
        return match[2] ? value.includes(match[3]) : value === match[3];
      });
    }, querySelectorAll: () => [], querySelector: () => null};
}
const free = image(freeId), oldFree = image(oldFreeId), card = image(freeId, false), theatre = image(theatreId, false), vip = image(vipId);
const unrelated = image('unrecognized');
const shortDrama = image(shortDramaId, false);
const images = [free, oldFree, card, theatre, vip, unrelated, shortDrama];
const document = {nodeType: 9, querySelectorAll: selector => images.filter(img => img.matches(selector)),
  querySelector: selector => images.find(img => img.matches(selector))};
const context = vm.createContext({document, tr: value => value,
  setUiAttribute: (el, key, value) => {if (el.getAttribute(key) !== value) el.setAttribute(key, value)}});
const targets = source.match(/var FIXED_UI_TARGETS = \[[\s\S]*?\]\.join\(","\);/)[0];
vm.runInContext(targets + '\n' + source.slice(source.indexOf('  function queryFixed('), source.indexOf('  function translateDocumentTitle(')), context);
context.localizeFixedUI();
const svg = img => decodeURIComponent(img.getAttribute('src').split(',')[1]);
for (const img of [free, oldFree]) {
  assert.equal(img.alt, 'Miễn phí có hạn');
  assert.equal(img.getAttribute('title'), 'Miễn phí có hạn');
  assert.match(svg(img), />Miễn phí<\/text>/);
  assert.equal(img.style.width, '58px');
}
assert.match(svg(card), />Miễn phí có hạn<\/text>/);
assert.equal(card.style.width, '104px');
assert.match(svg(theatre), />Rạp tình cảm<\/text>/);
assert.match(svg(shortDrama), />Phim ngắn chọn lọc<\/text>/);
assert.equal(shortDrama.alt, 'Phim ngắn chọn lọc');
assert.ok(context.hasFixedUI(image(shortDramaId, false)), 'Short-drama header images are recognized when inserted dynamically');
assert.equal(vip.alt, 'VIP');
assert.ok(unrelated.getAttribute('src').endsWith('/unrecognized.svg'));
assert.ok(context.hasFixedUI(image(freeId)), 'Dynamically inserted free badges enter the fixed UI path');
assert.ok(context.hasFixedUI(image(theatreId, false)));
const first = free.getAttribute('src');
context.localizeFixedUI();
assert.equal(free.getAttribute('src'), first, 'Repeated localization is stable');
free.setAttribute('src', 'https://static-s.iqiyi.com/lequ/' + vipId + '.svg');
context.localizeFixedUI(free);
assert.equal(free.alt, 'VIP', 'A recycled image must follow its new source, not its old saved badge ID');
const inserted = image(freeId);
context.localizeFixedUI(inserted);
assert.equal(inserted.alt, 'Miễn phí có hạn');
console.log('Badge checks passed: new/legacy free badges, compact labels, theatre, dynamic insertion, recycled VIP and unrelated images.');
