// Run: node test-sub-hook.cjs
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync(`${__dirname}/sub-hook.js`, "utf8");
const payload = tvid => ({data: {tvid, dstl: "https://meta.video.iqiyi.com",
  program: {stl: [{lid: 1, xml: "/source.xml"}]}}});
function runtime(pathname, playPageInfo, options = {}) {
  const calls = [];
  const intervals = [];
  const timeouts = [];
  const listeners = {};
  class Node {
    appendChild(node) { node.parentNode = this; return node; }
    insertBefore(node) { return this.appendChild(node); }
  }
  class XHR {
    open(method, url) { this.url = url; }
    send() {}
    addEventListener() {}
    get responseText() { return this.raw; }
    get response() { return this.raw; }
  }
  const document = {cookie: options.cookie || "", body: new Node(), head: new Node(), documentElement: new Node(),
    getElementById: () => null, querySelectorAll: () => [],
    addEventListener(type, fn) { listeners[type] = fn; },
    createElement: tag => ({tagName: tag.toUpperCase(), style: {}, setAttribute() {}})};
  const window = {Node, XMLHttpRequest: XHR, document, Q: {PageInfo: {playPageInfo}}, QySdk: options.sdk,
    __iqiyiViToken: options.noToken ? "" : "test-token", location: {hostname: options.hostname || "www.iqiyi.com", pathname,
      href: `https://www.iqiyi.com${pathname}`},
    setInterval: fn => { intervals.push(fn); return 1; },
    setTimeout: fn => { timeouts.push(fn); return timeouts.length; },
    fetch: async (url, init) => {
      calls.push({url, init});
      if (url.includes("/api/extension-token")) return Response.json({token: "test-token"});
      if (url.includes("/api/translation-state")) return Response.json({available: true, translating: false});
      if (url.includes("/api/register")) return Response.json({ok: true});
      if (url.includes("/dash")) return Response.json(payload("1233430264130200"));
      return new Response("<xml />", {headers: {"content-type": "text/xml"}});
    }};
  vm.runInNewContext(source, {window, URL, Headers, Response});
  return {window, calls, XHR, intervals, timeouts, listeners};
}
function assertTrack(body, tvid) {
  const tracks = body.data.program.stl;
  assert.equal(tracks[0].xml, "https://meta.video.iqiyi.com/source.xml");
  const vi = tracks.filter(track => track.lid === 23);
  assert.equal(vi.length, 1);
  assert.equal(vi[0].xml, `http://127.0.0.1:18766/subtitle.xml?tvid=${tvid}`);
  assert.equal(vi[0].name, "Tiếng Việt (AI)");
  return vi[0];
}
const rewrite = require("./sub-hook.js").rewrite;
for (const [url, prefix] of [
  ["http://meta.video.iqiyi.com/20250723/6f/c0/b0057f6acb941235729748dc1c4a37ca.xml", ""],
  ["/20250723/6f/c0/b0057f6acb941235729748dc1c4a37ca.xml", "http://meta.video.iqiyi.com"],
  ["//meta.video.iqiyi.com/20250723/6f/c0/b0057f6acb941235729748dc1c4a37ca.xml", "http://meta.video.iqiyi.com"],
  ["b0057f6acb941235729748dc1c4a37ca.xml", "http://meta.video.iqiyi.com/20250723/6f/c0/"]
]) {
  const body = rewrite({data: {tvid: "1233430264130200", dstl: prefix,
    program: {stl: [{lid: 1, xml: url}]}}});
  assert.equal(body.data.program.stl[0].xml,
    "https://meta.video.iqiyi.com/20250723/6f/c0/b0057f6acb941235729748dc1c4a37ca.xml");
  assert.match(body.data.program.stl[1].xml, /^http:\/\/127\.0\.0\.1:18766\//);
}
(async () => {
  const web = runtime("/", null, {cookie: "P00001=web-test-auth; P00003=12345; QC005=web-device; __dfp=web-fingerprint%401234", noToken: true});
  await new Promise(resolve => setImmediate(resolve));
  const sessions = r => r.calls.filter(call => call.url.endsWith("/api/session")).map(call => JSON.parse(call.init.body));
  assert.equal(sessions(web)[0].source, "web", "Homepage must sync web login even before token discovery finishes");
  assert.equal(sessions(web)[0].authcookie, "web-test-auth");
  assert.equal(sessions(web)[0].uid, "12345");
  assert.equal(sessions(web)[0].deviceId, "web-device");
  assert.equal(sessions(web)[0].dfp, "web-fingerprint");
  web.intervals.forEach(fn => fn());
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(sessions(web).length, 1, "Unchanged login is throttled");
  web.window.document.cookie = "";
  web.intervals.forEach(fn => fn());
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(sessions(web).at(-1).authcookie, "", "Logout must clear only the web session");
  web.window.document.cookie = 'P00001=web-new-auth; P00002=' + encodeURIComponent(JSON.stringify({uid: "67890"}));
  web.intervals.forEach(fn => fn());
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(sessions(web).at(-1).uid, "67890", "Encoded user cookie supplies missing P00003");
  const native = runtime("/index.html", null, {hostname: "localwebapp.iqiyi.com",
    sdk: {Account: {getLoginInfo: () => ({cache: {authcookie: "app-test-auth", uid: "98765"}})}}});
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(sessions(native)[0].source, "app");
  assert.equal(sessions(native)[0].authcookie, "app-test-auth");
  const guest = runtime("/", null, {cookie: "P00001=%bad; P00003=invalid"});
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(sessions(guest)[0].authcookie, "", "Malformed cookies cannot become credentials");
  assert.equal(fs.readFileSync(`${__dirname}/ext/sub-hook.js`, "utf8").replace(/\r\n/g, "\n"), source.replace(/\r\n/g, "\n"), "Extension hook must match shared hook");
  const menu = runtime("/v_menu123.html");
  const attributes = new Map();
  const option = {nodeType: 1, tagName: "BUTTON", parentElement: menu.window.document.body,
    textContent: " Tiếng Việt (AI) ", disabled: false, style: {opacity: "", cursor: ""},
    get innerText() { throw new Error("Subtitle menu must not force layout"); },
    getAttribute: name => attributes.get(name) ?? null,
    setAttribute: (name, value) => attributes.set(name, value),
    removeAttribute: name => attributes.delete(name)};
  menu.window.document.querySelectorAll = () => [option];
  menu.window.__iqiyiSubtitleEngine.rewrite(payload("1233430264130200"));
  menu.timeouts.splice(0).forEach(fn => fn());
  assert.equal(option.disabled, true, "Unavailable track must remain disabled");
  let blocked = false;
  menu.listeners.click({target: option, preventDefault() { blocked = true; }, stopPropagation() {}});
  assert(blocked, "Unavailable track selection must be blocked without reading innerText");
  await new Promise(resolve => setImmediate(resolve));
  menu.timeouts.splice(0).forEach(fn => fn());
  assert.equal(option.disabled, false, "Available track must become selectable");
  assert.equal(option.getAttribute("aria-disabled"), null);
  assert.equal(option.style.opacity, "");
  assert.equal(option.style.cursor, "");
  blocked = false;
  menu.listeners.click({target: option, preventDefault() { blocked = true; }, stopPropagation() {}});
  assert.equal(blocked, false);
  const detected = runtime("/v_bb6gsxzz78.html", {tvId:"1233430264130200", albumId:"2131053845257801", tvName:"逍遥 第1集"});
  await new Promise(resolve => setImmediate(resolve));
  const registered = detected.calls.find(call => call.url.endsWith("/api/register"));
  assert(registered, "Web metadata must register without subtitle traffic");
  assert.equal(JSON.parse(registered.init.body).albumTitle, "逍遥");
  for (const extra of [{}, {albumName:"雀骨"}, {album:{name:"雀骨"}}]) {
    const description = runtime("/v_test123456.html", {tvId:"8493031186391200",
      albumId:"3493131454654001", title:"无衣嘉鱼的混乱初遇", order:1, ...extra});
    await new Promise(resolve => setImmediate(resolve));
    const registration = description.calls.find(call => call.url.endsWith("/api/register"));
    assert(registration, "Keep registering IDs when only the episode description is known");
    assert.equal(JSON.parse(registration.init.body).albumTitle,
      extra.albumName || extra.album?.name, "Do not infer the movie name from a description");
  }
  detected.window.__iqiyiSubtitleEngine.rewrite({albumId:"3493131454654001", episodes:[{
    tvId:"8493031186391200", entityTitle:"无衣嘉鱼的混乱初遇", name:"雀骨第1集", order:1
  }]});
  await new Promise(resolve => setImmediate(resolve));
  const albumRegistration = detected.calls.find(call => call.url.endsWith("/api/album/register"));
  assert(albumRegistration, "Episode list must register its movie name");
  assert.equal(JSON.parse(albumRegistration.init.body).title, "雀骨");
  const invalid = runtime("/v_bb6gsxzz78.html", {tvId:"invalid", albumId:"2131053845257801"});
  await new Promise(resolve => setImmediate(resolve));
  assert(!invalid.calls.some(call => call.url.endsWith("/api/register")));
  const modern = runtime("/v_19rqw1wswc.html");
  modern.window.playbackPageStageStatus = {_accData:{videoInfo:{tvId:"1908130400",albumId:"123456789",name:"招摇 第1集",album:{name:"招摇"}}}};
  modern.intervals.forEach(fn => fn());
  await new Promise(resolve => setImmediate(resolve));
  const modernRegistration = modern.calls.find(call => call.url.endsWith("/api/register"));
  assert(modernRegistration, "Modern player must register after delayed metadata arrival");
  assert.equal(JSON.parse(modernRegistration.init.body).albumTitle, "招摇");
  const count = modern.calls.filter(call => call.url.endsWith("/api/register")).length;
  modern.intervals.forEach(fn => fn());
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(modern.calls.filter(call => call.url.endsWith("/api/register")).length,count);
  const preloaded = runtime("/v_bb6gsxzz78.html");
  const xor = text => text.split("").map(c=>String.fromCharCode(c.charCodeAt(0)^90)).join("");
  for (const id of ["1233430264130200","1847889303707600","2072495740548000","2783214681050800","3886994887494000","4114007823147000","4487014942701200","7156622883680000","7947558409134200","8811491027499200"]) {
    const original = {ev:xor(JSON.stringify(payload(id))), videoInfo:{tvId:id,albumId:"1978642334195801",title:"测试"}};
    preloaded.window.QiyiPlayerProphetData = original;
    assertTrack(JSON.parse(xor(preloaded.window.QiyiPlayerProphetData.ev)), id);
    assert.equal(JSON.parse(xor(original.ev)).data.program.stl.length,1,"Keep original input untouched");
  }
  const acceleratorPath = `${__dirname}/.local/iqiyi-accelerator.js`;
  if (fs.existsSync(acceleratorPath)) {
    const raw = fs.readFileSync(acceleratorPath,"utf8").match(/window\.QiyiPlayerProphetData = ([^\n]+);/);
    assert(raw, "Expected accelerator assignment");
    const actual = JSON.parse(raw[1]);
    if (actual.ev) {
      preloaded.window.QiyiPlayerProphetData = actual;
      const tracks = JSON.parse(xor(preloaded.window.QiyiPlayerProphetData.ev)).data.program.stl;
      const injected = tracks.find(t => t.lid === 23);
      assert(injected, "Real accelerator response must contain local Vietnamese track");
      assert.equal(injected.xml, `http://127.0.0.1:18766/subtitle.xml?tvid=${actual.tvId}`);
      console.log("PASS: real iQIYI accelerator payload connects to translated XML");
    }
  }
  const malformed = {ev:"not encoded JSON"};
  preloaded.window.QiyiPlayerProphetData = malformed;
  assert.equal(preloaded.window.QiyiPlayerProphetData,malformed);
  // Native app and web fetch both feed the same rewritten track to the player.
  for (const path of ["/player.html", "/v_bb6gsxzz78.html"]) {
    const {window, calls, XHR} = runtime(path);
    const body = await (await window.fetch("https://cache.video.iqiyi.com/dash")).json();
    assert.equal(assertTrack(body, "1233430264130200").main, 1);
    const xhr = new XHR();
    xhr.open("GET", "https://cache.video.iqiyi.com/dash");
    xhr.readyState = 4; xhr.responseType = "text"; xhr.raw = JSON.stringify(payload("4114007823147000"));
    assertTrack(JSON.parse(xhr.responseText), "4114007823147000");
    await new Promise(resolve => setImmediate(resolve));
    assert(calls.some(call => call.url.endsWith("/api/register") &&
      JSON.parse(call.init.body).tvid === "1233430264130200"));
  }
  const {window, calls} = runtime("/v_bb6gsxzz78.html");
  for (const method of ["appendChild", "insertBefore"]) {
    for (const tvid of ["1233430264130200", "4114007823147000"]) {
      let received;
      const extra = {keep: true};
      window.Qtest = function (body, arg) { assert.equal(this, window); assert.equal(arg, extra); received = body; delete window.Qtest; };
      const script = {tagName: "SCRIPT", src: "https://cache.video.iqiyi.com/dash?callback=Qtest"};
      assert.equal(window.document.head[method](script, null), script);
      await window.Qtest(payload(tvid), extra);
      assert.equal(assertTrack(received, tvid).main, 1);
      assert.equal(window.Qtest, undefined);
    }
  }
  let untouched;
  const ordinary = body => { untouched = body; };
  window.Qtest = ordinary;
  window.document.head.appendChild({tagName: "SCRIPT", src: "https://example.org/dash?callback=Qtest"});
  assert.equal(window.Qtest, ordinary);
  window.document.head.appendChild({tagName: "SCRIPT", src: "https://pcw-api.iqiyi.com/info?cb=Qtest"});
  const metadata = {code: "A00000", data: {title: "临江仙"}};
  window.Qtest(metadata);
  assert.equal(untouched, metadata);
  assert(!calls.some(call => call.url.includes("/api/episodes")));
  assert(!source.includes("iqiyi-vi-managed-subtitle"));
  assert.equal(fs.readFileSync(`${__dirname}/ext/sub-hook.js`, "utf8").replace(/\r\n/g, "\n"), source.replace(/\r\n/g, "\n"));
  console.log("PASS: app/web fetch + XHR + JSONP, native Vietnamese track, episode switch, callback cleanup/arguments, unrelated scripts, extension sync");
})().catch(error => { console.error(error); process.exitCode = 1; });
