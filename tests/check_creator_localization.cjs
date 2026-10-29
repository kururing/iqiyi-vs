/* Run: node tests/check_creator_localization.cjs */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../ext/content.js'), 'utf8');
function leaf(component, original) {
  const attrs = new Map(), node = {nodeType: 3, nodeValue: original};
  const el = {nodeType: 1, className: component + '__test', firstChild: node, childNodes: [node],
    get textContent() { return node.nodeValue; },
    getAttribute: key => attrs.get(key) || null,
    setAttribute: (key, value) => attrs.set(key, value),
    matches: selector => selector === '[class*="' + component + '__"]',
    querySelectorAll: () => [],
    __reactFiber$test: {memoizedProps: {children: original}}};
  node.parentElement = el;
  return el;
}
const statLabels = ['获赞','关注','粉丝'].map(value => leaf('info_starStatLabel', value));
const units = ['万','亿'].map(value => leaf('info_starStatUnit', value));
const fields = ['英文名','国籍','出生日期','毕业院校','血型'].map(value => leaf('aboutTa_label', value));
const stats = {nodeType: 1, matches: selector => selector === '[class*="info_starStats__"]',
  querySelectorAll: selector => [...statLabels, ...units].filter(el => el.matches(selector))};
const all = [stats, ...fields];
const document = {nodeType: 9, querySelectorAll: selector => all.filter(el => el.matches(selector))};
const context = vm.createContext({document, MACHINE_RENDERED: new WeakMap(), IQCOM_METADATA_FALLBACK: new WeakMap(),
  tr: value => { throw Error('Fixed creator labels must not wait for machine translation: ' + value); },
  setUiAttribute: (el, key, value) => el.setAttribute(key, value)});
vm.runInContext(source.slice(source.indexOf('  var FIXED_COPY ='), source.indexOf('  function cjkCount(')) +
  source.match(/var FIXED_UI_TARGETS = \[[\s\S]*?\]\.join\(","\);/)[0] +
  source.slice(source.indexOf('  function actorSourceText('), source.indexOf('  function pumpIqcomMetadata(')) +
  source.slice(source.indexOf('  function queryFixed('), source.indexOf('  function translateDocumentTitle(')), context);
// A stale machine result should be repaired using the component's original props.
statLabels[2].firstChild.nodeValue = 'cái quạt';
units[0].firstChild.nodeValue = 'Mười nghìn';
const originalNodes = [...statLabels, ...units, ...fields].map(el => el.firstChild);
context.localizeFixedUI();
assert.deepEqual(statLabels.map(el => el.textContent), ['Lượt thích','Đang theo dõi','Người hâm mộ']);
assert.deepEqual(units.map(el => el.textContent), ['vạn','trăm triệu']);
assert.deepEqual(fields.map(el => el.textContent), ['Tên tiếng Anh','Quốc tịch','Ngày sinh','Trường tốt nghiệp','Nhóm máu']);
context.localizeFixedUI();
assert.deepEqual([...statLabels, ...units, ...fields].map(el => el.firstChild), originalNodes,
  'Keep React-owned text nodes and control bindings');
units[0].firstChild.nodeValue = '亿';
units[0].__reactFiber$test.memoizedProps.children = '亿';
context.localizeFixedUI(stats);
assert.equal(units[0].textContent, 'trăm triệu', 'Reused counters must follow the new unit');
console.log('Creator checks passed: synchronous field labels, compact units, stale machine copy, React text identity and updated counters.');
