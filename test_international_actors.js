// Run with: node test_international_actors.js
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

let calls = [];
let replies = {"许凯":"Hứa Khải", "白鹿":"Bạch Lộc", "罗云熙":"La Vân Hi"};
const context = {
  window: {__iqiyiViToken:"test-token", fetch:true, __iqiyiViDict:{"许凯":"Wrong", "演员":"Diễn viên "}},
  location: {pathname:"/index.html", href:"https://localwebapp.iqiyi.com/index.html"},
  document: {getElementById:() => null},
  localStorage: {length:0, getItem:() => "{}"},
  fetch: async (url, options) => {
    assert.equal(options.headers["X-Iqiyi-Token"], "test-token");
    assert.equal(new URL(url).pathname, "/api/international-actor");
    const name = new URL(url).searchParams.get("name");
    calls.push(name);
    return {ok:true, json:async () => ({sourceName:name, name:replies[name] || "", id:"123"})};
  }
};
let source = fs.readFileSync(__dirname + "/ui-engine.js", "utf8");
// Load the real walker and helpers without starting the document observer/timer.
source = source.slice(0, source.indexOf("  function run()")) + "globalThis.walk = walk; globalThis.isActorNameNode = isActorNameNode;})();";
vm.runInNewContext(source, context);

function actor(text, className = "metaAlbumSideLayer_actorNameText__0Wp6w") {
  const node = {nodeType:3, nodeValue:text, isConnected:true};
  const el = {nodeType:1, tagName:"SPAN", id:"", className, childElementCount:0,
    childNodes:[node], firstChild:node, isConnected:true, getAttribute:() => null};
  Object.defineProperty(el, "textContent", {get:() => node.nodeValue});
  node.parentElement = el;
  return {el, node};
}
const settle = () => new Promise(resolve => setImmediate(resolve));

(async () => {
  const verifiedCast = actor("曾舜晞 / 田曦薇");
  context.walk(verifiedCast.el);
  await settle();
  assert.equal(verifiedCast.node.nodeValue, "Tăng Thuấn Hy / Điền Hi Vi");
  assert.deepEqual(calls, [], "Use verified Vietnamese cast names without metadata requests");

  const first = actor("许凯"), duplicate = actor("许凯");
  context.walk(first.el);
  context.walk(duplicate.el);
  await settle();
  assert.equal(first.node.nodeValue, "Hứa Khải");
  assert.equal(duplicate.node.nodeValue, "Hứa Khải");
  assert.deepEqual(calls, ["许凯"]);
  const direct = actor("许凯");
  context.walk(direct.node);
  await settle();
  assert.equal(direct.node.nodeValue, "Hứa Khải");
  const attributes = actor("许凯");
  const attrs = {title:"许凯",alt:"许凯"};
  attributes.el.getAttribute = key=>attrs[key] || null;
  attributes.el.setAttribute = (key,value)=>{attrs[key]=value;};
  context.walk(attributes.el);
  await settle();
  assert.equal(attrs.title,"Hứa Khải");
  assert.equal(attrs.alt,"Hứa Khải");
  assert.equal(attributes.node.nodeValue,"Hứa Khải");

  const list = actor("许凯 / 白鹿", "albumMeta_albumMetaOpenCastItem__Az7ej");
  context.walk(list.el);
  await settle();
  assert.equal(list.node.nodeValue, "Hứa Khải / Bạch Lộc");
  const heading = actor("演员许凯", "info_starNameText__CT6Pj");
  context.walk(heading.el);
  await settle();
  assert.equal(heading.node.nodeValue, "Diễn viên Hứa Khải");

  const stale = actor("许凯");
  context.walk(stale.el);
  stale.node.nodeValue = "新演员";
  await settle();
  assert.equal(stale.node.nodeValue, "新演员");
  const unknown = actor("未知演员");
  context.walk(unknown.el);
  await settle();
  assert.equal(unknown.node.nodeValue, "未知演员");
  const oldTranslation = actor("Old machine name", "filmFeed_actName__jCTab");
  oldTranslation.el.__reactFiber$test = {memoizedProps:{children:"许凯"}};
  context.walk(oldTranslation.el);
  await settle();
  assert.equal(oldTranslation.node.nodeValue, "Hứa Khải");
  const oldUnknown = actor("Wrong cached name", "filmFeed_actName__jCTab");
  oldUnknown.el.__reactFiber$test = {memoizedProps:{children:"未知演员"}};
  context.walk(oldUnknown.el);
  await settle();
  assert.equal(oldUnknown.node.nodeValue, "未知演员");
  const recycled = actor("Old machine name", "filmFeed_actName__jCTab");
  recycled.el.__reactFiber$test = {memoizedProps:{children:"许凯"}};
  context.walk(recycled.el);
  recycled.el.__reactFiber$test.memoizedProps.children = "白鹿";
  await settle();
  assert.equal(recycled.node.nodeValue, "Old machine name");
  const nativePlayerActor = actor("罗云熙", "meta_tag__XjB9X meta_tagBtn__ImyT4");
  nativePlayerActor.el.getAttribute = name => name === "data-ai-entity" ? "TVG演员筛选标签,TVG主演标签二级页入口" : null;
  context.walk(nativePlayerActor.el);
  await settle();
  assert.equal(nativePlayerActor.node.nodeValue, "La Vân Hi");
  assert.deepEqual(calls.slice(-1), ["罗云熙"]);
  const noToken = actor("白鹿");
  context.window.__iqiyiViToken = "";
  context.walk(noToken.el);
  await settle();
  assert.equal(noToken.node.nodeValue, "白鹿");
  assert.equal(context.isActorNameNode(actor("设置", "info_starNameTag__QQtfF").el), false);
  assert.equal(context.isActorNameNode(actor("招摇", "flexVideoList_title__pTP9Y").el), false);
  console.log("Actor API rendering checks passed.");
})().catch(error => { console.error(error); process.exitCode = 1; });
