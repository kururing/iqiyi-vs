// Run with: node test_fixed_ui.js
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

function element(text = "") {
  const el = {nodeType:1, childNodes:[], style:{}, attrs:{},
    getAttribute(name) {return this.attrs[name] || null;},
    setAttribute(name, value) {this.attrs[name] = value;},
    closest() {return this.attrs["data-iqiyi-vi-fixed"] ? this : null;},
    appendChild(node) {this.childNodes.push(node);this.firstChild = this.childNodes[0];node.parentElement = this;}};
  if (text) el.appendChild({nodeType:3,nodeValue:text});
  return el;
}
const vip = element("会员特惠"), channel = element(), search = element();
const following = element(), limited = element();
limited.getBoundingClientRect = () => ({width:28,height:12});
following.attrs.src = "https://example.test/9013485acf0c4e07a2500429869d44f4.svg";
limited.attrs.src = "https://example.test/5a2c3f02c5b54771b1047a27cc1f0447.svg";
const selectors = new Map([
  ["#userCenterSpan", [vip]],
  ['#searchinput input[type="text"]', [search]],
  ['[class*="cardMemos_channelmark2__"]', [channel]]
]);
const context = {
  window: {__iqiyiViDict:{"正片":"Sai", "旧标签":"Nhãn cũ"},__iqiyiViTitles:{"旧片名":"Tên cũ"}}, location:{pathname:"/",href:"https://www.iqiyi.com/"},
  localStorage:{length:0,getItem:()=>"{}"},
  document:{getElementById:()=>null,createTextNode:text=>({nodeType:3,nodeValue:text}),
    querySelectorAll(selector) {
      const match = selector.match(/^img\[src\*="([^"]+)"\]$/);
      return match ? [following, limited].filter(el=>el.attrs.src.includes(match[1])) : selectors.get(selector) || [];
    }},
  fetch:()=>assert.fail("Fixed labels must not call translation APIs")
};
let source = fs.readFileSync(__dirname + "/ui-engine.js", "utf8");
source = source.slice(0,source.indexOf("  function run()")) +
  "globalThis.localizeFixedUI=localizeFixedUI;globalThis.walk=walk;globalThis.tr=tr;globalThis.autoTranslateMixed=autoTranslateMixed;})();";
vm.runInNewContext(source,context);
context.localizeFixedUI();
assert.equal(vip.firstChild.nodeValue,"Trung tâm VIP");
assert.equal(search.attrs.placeholder,"Tìm phim, diễn viên…");
assert.equal(channel.firstChild.nodeValue,"Phim bộ");
assert.equal(channel.style.backgroundImage,"none");
assert.equal(following.attrs.alt,"Đang theo dõi");
assert.equal(limited.attrs.alt,"Miễn phí có hạn");
assert.match(decodeURIComponent(limited.attrs.src), /width="28" height="12"/);
assert.equal(limited.style.width,undefined);
assert.equal(limited.style.height,undefined);
assert.equal(context.tr("正片"),"Tập chính");
assert.equal(context.tr("专访"),"Phỏng vấn");

assert.equal(context.window.__iqiyiViAutoStatus().enabled,true);
assert.match(decodeURIComponent(following.attrs.src),/>Đang theo dõi<\/text>/);
assert.equal(following.attrs.src.includes("example.test"),false);
// Fixed labels and their attributes bypass the generic dictionary walker.
context.walk(vip);
assert.equal(vip.firstChild.nodeValue,"Trung tâm VIP");
const originalNode = vip.firstChild;
context.localizeFixedUI();
assert.equal(vip.firstChild,originalNode);
assert.equal(channel.childNodes.length,1);
// React can reuse a badge image for a different permission state.
following.attrs.src = "https://example.test/5a2c3f02c5b54771b1047a27cc1f0447.svg";
context.localizeFixedUI();
assert.equal(following.attrs.alt,"Miễn phí có hạn");
console.log("Fixed Vietnamese labels and badge replacement checks passed.");

for (const [source, expected] of [
  ["会员特惠，新人专享","Ưu đãi VIP dành cho khách mới"],
  ["同时播放1台","Phát đồng thời trên 1 thiết bị"],
  ["已兑换4.2w件","Đã đổi 4.2 vạn lượt"],
  ["首月1分钱","Tháng đầu 0,01 tệ"],
  ["本周二更新","Cập nhật thứ Ba tuần này"],
  ["古装探案榜No.9","Phá án cổ trang · BXH số 9"],
  ["不看：古装爱情","Không xem: Tình cảm cổ trang"],
  ["256部新片即将上映","256 phim mới sắp ra mắt"],
  ["综艺榜","BXH giải trí"],
  ["动漫榜","BXH anime"],
  ["未知电影名字","未知电影名字"]
]) assert.equal(context.tr(source),expected,source);
assert.equal(context.tr("未知1分钱"),"未知1分钱", "No partial template translation");
console.log("Observed VIP/homepage phrases, complete templates and unknown-text checks passed.");

assert.equal(context.tr("旧标签"),"旧标签","Legacy UI dictionaries must be ignored");
assert.equal(context.tr("旧片名"),"旧片名","Legacy film title tables must be ignored");
assert.equal(context.window.__iqiyiViDict,undefined);
assert.equal(context.window.__iqiyiViTitles,undefined);
