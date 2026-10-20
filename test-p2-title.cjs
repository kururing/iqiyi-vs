// Run: node test-p2-title.cjs
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync(`${__dirname}/ui-engine.js`, "utf8");
const id = "1234567890123456";
const context = vm.createContext({URL, location: {href: `https://www.iqiyi.com/v_${id}.html`},
  window: {}, INTERNATIONAL_TITLE_CACHE: {[id]: {title: "Tên phim chính thức", expires: Date.now() + 60000}},
  INTERNATIONAL_TITLE_PENDING: {}});
vm.runInContext(source.slice(source.indexOf("  function cjkCount("), source.indexOf("  // Các chuỗi")), context);
function element(tagName, attrs = {}, parentElement = null) {
  return {nodeType: 1, tagName, className: attrs.class || "", id: attrs.id || "", parentElement,
    getAttribute: key => attrs[key] || null};
}
function text(parentElement, nodeValue) { return {nodeType: 3, parentElement, nodeValue, isConnected: true}; }
const anchor = element("A", {href: `/v_${id}.html`});
for (const node of [text(element("SPAN", {}, anchor), "立即播放"),
                    text(element("SPAN", {class: "description"}, anchor), "剧情描述"),
                    text(element("BUTTON", {}, anchor), "立即播放"),
                    text(element("SPAN", {class: "badge"}, anchor), "会员专享")]) {
  assert.equal(context.findInternationalTitleId(node), "");
  assert.equal(context.requestInternationalTitle(node, node.nodeValue, () => assert.fail("Non-title replaced")), false);
}
const card = element("DIV", {"data-albumid": id});
assert.equal(context.findInternationalTitleId(text(element("P", {class: "description"}, card), "剧情描述")), "");
for (const node of [text(element("SPAN", {class: "title"}, anchor), "雀骨"),
                    text(element("H2", {}, anchor), "雀骨"),
                    text(element("SPAN", {class: "movieTitle"}, card), "雀骨"),
                    text(element("H1"), "雀骨"), text(element("TITLE"), "雀骨")]) {
  assert.equal(context.findInternationalTitleId(node), id);
  let translated;
  assert.equal(context.requestInternationalTitle(node, node.nodeValue, value => translated = value), true);
  assert.equal(translated, "Tên phim chính thức");
}
const normalize = value => value.replace(/\r\n/g, "\n");
assert.equal(normalize(fs.readFileSync(`${__dirname}/ext/content.js`, "utf8")), normalize(source));
assert(normalize(fs.readFileSync(`${__dirname}/lwa-vi.js`, "utf8")).endsWith(normalize(source)));
console.log("PASS: only title nodes use movie metadata; action/description/badge labels stay independent; bundles synchronized");
