'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, 'sub-hook.js'), 'utf8');
const token = 'offline-player-token';
const flush = () => new Promise(resolve => setImmediate(resolve));
const reply = (status = 200, text = '{}', type = 'application/json') => new Response(text, {status, headers: {'content-type': type}});

function player(transport) {
  const window = {__iqiyiViToken: token, location: {pathname: '/player.html', hostname: ''},
    fetch: transport, setTimeout(callback) { queueMicrotask(callback); }};
  vm.runInNewContext(source, {window, console, Map, Set, Promise, Response, Headers});
  return window;
}

function metadata(withVietnamese = false) {
  const tracks = [{lid: 1, name: 'Source', xml: 'https://meta.video.iqiyi.com/source.xml'},
    {lid: 2, name: 'Other language', srt: '/other.srt'}];
  if (withVietnamese) tracks.push({lid: 23, name: 'Existing Vietnamese', xml: 'https://meta.video.iqiyi.com/original-vi.xml'});
  return {tvId: '101', title: 'Show', albumId: '9', prefix: 'https://meta.video.iqiyi.com/', subtitleData: {data: tracks}};
}

async function tracksAndAuth() {
  const calls = [];
  const window = player(async (url, options) => { calls.push({url, options}); return reply(); });
  const rewrite = window.__iqiyiSubtitleEngine.rewrite;
  const existing = rewrite(metadata(true));
  assert.equal(existing.subtitleData.data.filter(x => x.lid === 23).length, 1);
  assert.equal(existing.subtitleData.data.find(x => x.lid === 23).xml, 'https://meta.video.iqiyi.com/original-vi.xml');
  const rewritten = rewrite(metadata());
  const ai = rewritten.subtitleData.data.find(x => x.lid === 23);
  assert.equal(ai.xml, 'http://127.0.0.1:18766/subtitle.xml?tvid=101&token=' + token);
  assert.equal(rewritten.subtitleData.data.find(x => x.lid === 2).srt, 'https://meta.video.iqiyi.com/other.srt');
  assert.equal(rewrite(rewritten).subtitleData.data.filter(x => x.lid === 23).length, 1);
  await flush();
  assert(calls.length > 0);
  calls.forEach(call => assert.equal(call.options.headers['X-Iqiyi-Token'], token));
  console.log('PASS: original tracks preserved, injected track is unique, API requests authenticated');
}

async function retryRegistration() {
  let attempts = 0, available = false;
  const window = player(async () => { attempts++; return reply(available ? 200 : 503); });
  window.__iqiyiSubtitleEngine.rewrite(metadata());
  await flush();
  assert.equal(attempts, 4);
  available = true;
  window.__iqiyiSubtitleEngine.rewrite(metadata());
  await flush();
  assert.equal(attempts, 5);
  window.__iqiyiSubtitleEngine.rewrite(metadata());
  await flush();
  assert.equal(attempts, 5);
  console.log('PASS: registration retries transient failures and deduplicates only successful requests');
}

async function captureWaitsForRegistrationAndUsesPreferredTrack() {
  const calls = [];
  let finishRegistration;
  const window = player((url, options) => {
    calls.push({url, options});
    if (url.endsWith('/api/register')) return new Promise(resolve => { finishRegistration = resolve; });
    if (url.endsWith('.xml') || url.endsWith('.srt')) return Promise.resolve(reply(200, '<xml />', 'text/xml'));
    return Promise.resolve(reply());
  });
  window.__iqiyiSubtitleEngine.rewrite(metadata());
  await window.fetch('https://meta.video.iqiyi.com/source.xml');
  await flush();
  assert.equal(calls.filter(x => x.url.endsWith('/api/capture')).length, 0);
  finishRegistration(reply());
  await flush();
  await flush();
  const captures = calls.filter(x => x.url.endsWith('/api/capture'));
  assert.equal(captures.length, 1);
  assert.equal(captures[0].options.headers['X-Iqiyi-Token'], token);
  assert.equal(JSON.parse(captures[0].options.body).tvid, '101');
  await window.fetch('https://meta.video.iqiyi.com/other.srt');
  await flush();
  assert.equal(calls.filter(x => x.url.endsWith('/api/capture')).length, 1);
  console.log('PASS: capture waits for registration and other languages cannot replace the chosen source');
}

async function staleUiTranslation() {
  const text = {nodeType: 3, nodeValue: '旧标题', isConnected: true};
  const element = {nodeType: 1, tagName: 'DIV', id: '', className: '', childNodes: [text], firstChild: text,
    childElementCount: 0, get textContent() { return text.nodeValue; }, getAttribute() { return null; }};
  let finish;
  const window = {__iqiyiViDict: {}};
  const sandbox = {window, location: {pathname: '/index.html'}, localStorage: {getItem() { return null; }, setItem() {}},
    document: {body: {}, documentElement: element, getElementById() { return {remove() {}}; },
      querySelector() { return null; }, querySelectorAll() { return []; }},
    fetch() { return new Promise(resolve => { finish = resolve; }); }, Promise,
    setInterval() { return 1; }, clearInterval() {}, setTimeout() { return 1; },
    MutationObserver: class { observe() {} disconnect() {} }, cancelAnimationFrame() {}};
  window.fetch = sandbox.fetch;
  vm.runInNewContext(fs.readFileSync(require('node:path').join(__dirname, 'ui-engine.js'), 'utf8'), sandbox);
  assert(finish);
  text.nodeValue = '新标题';
  finish({ok: true, json() { return Promise.resolve(['Old title Vietnamese']); }});
  await flush();
  assert.equal(text.nodeValue, '新标题');
  window.__iqiyiViReload({});
  finish({ok: true, json() { return Promise.resolve(['New title Vietnamese']); }});
  await flush();
  assert.equal(text.nodeValue, 'New title Vietnamese');
  console.log('PASS: late UI translations cannot overwrite reused nodes; current results still apply');
}

function uiCacheAndDictionaryReload() {
  let lookups = 0, tick;
  const text = {nodeType: 3, nodeValue: '首页', isConnected: true};
  const element = {nodeType: 1, tagName: 'DIV', id: '', className: '', childNodes: [text], firstChild: text,
    childElementCount: 0, get textContent() { return text.nodeValue; }, getAttribute() { return null; }};
  const dictionary = new Proxy({'首页': 'Trang chủ'}, {get(target, key) { lookups++; return target[key]; }});
  const window = {__iqiyiViDict: dictionary};
  const sandbox = {window, location: {pathname: '/index.html'}, localStorage: {getItem() { return null; }},
    document: {body: {}, documentElement: element, getElementById() { return {remove() {}}; },
      querySelector() { return null; }, querySelectorAll() { return []; }},
    setInterval(callback) { tick = callback; return 1; }, clearInterval() {}, setTimeout() { return 1; },
    MutationObserver: class { observe() {} disconnect() {} }, cancelAnimationFrame() {}};
  vm.runInNewContext(fs.readFileSync(require('node:path').join(__dirname, 'ui-engine.js'), 'utf8'), sandbox);
  assert.equal(text.nodeValue, 'Trang chủ');
  lookups = 0;
  for (let index = 0; index < 1000; index++) { text.nodeValue = '首页'; tick(); }
  assert.equal(lookups, 0);
  text.nodeValue = '首页';
  window.__iqiyiViReload({'首页': 'Trang chủ mới'});
  assert.equal(text.nodeValue, 'Trang chủ mới');
  console.log('PASS: 1,000 repeated translations reuse cache; reloading the dictionary invalidates it');
}

async function managerClientWiring() {
  const python = fs.readFileSync(require('node:path').join(__dirname, 'subtitle_app.py'), 'utf8');
  const page = python.match(/PAGE = r'''([\s\S]*?)'''/)[1];
  const script = page.match(/<script>([\s\S]*?)<\/script>/)[1].replace('__IQIYI_TOKEN__', JSON.stringify(token));
  const mockElement = () => { const classes = new Set(); return {value: '', className: '', textContent: '', innerHTML: '', hidden: false,
    disabled: false, classList: {toggle(name, force) { if (force ?? !classes.has(name)) classes.add(name); else classes.delete(name); }, add(name) { classes.add(name); }, remove(name) { classes.delete(name); }, contains(name) { return classes.has(name); }}, setAttribute() {},
    removeAttribute() {}, addEventListener() {}, querySelectorAll() { return []; }}; };
  const status = mockElement(), items = mockElement(), elements = new Map(), calls = [];
  let episodePayload = '{"episodes":[],"session":{"synced":false,"connected":false}}';
  const getElement = id => id === 'status' ? status : id === 'items' ? items :
    (elements.get(id) || elements.set(id, mockElement()).get(id));
  const sandbox = vm.createContext({location: {hash: ''}, window: {addEventListener() {}, scrollTo() {}},
    document: {getElementById: getElement},
    fetch: async (url, options) => { calls.push({url, options}); return reply(200, episodePayload); },
    setInterval() {}, setTimeout() { return 1; }, clearTimeout() {}, console});
  vm.runInContext(script, sandbox);
  await flush();
  const accountStatus = getElement('accountStatus');
  assert.equal(accountStatus.textContent, 'iQIYI chưa kết nối · Chưa xác định trạng thái đăng nhập');
  assert.equal(accountStatus.classList.contains('connected'), false);
  episodePayload = '{"episodes":[],"session":{"synced":true,"connected":true}}';
  await vm.runInContext('refresh(true)', sandbox);
  assert.equal(accountStatus.textContent, 'iQIYI đã kết nối · Đã đăng nhập');
  assert.equal(accountStatus.classList.contains('connected'), true);
  episodePayload = '{"episodes":[],"session":{"synced":true,"connected":false}}';
  await vm.runInContext('refresh(true)', sandbox);
  assert.equal(accountStatus.textContent, 'iQIYI đã kết nối · Chưa đăng nhập');
  assert.equal(accountStatus.classList.contains('connected'), true);
  const episodeListCall = calls.find(call => call.url === '/api/episodes');
  assert(episodeListCall);
  assert.equal(episodeListCall.options.headers['X-Iqiyi-Token'], token);
  vm.runInContext('render([{tvid:"101",albumId:"9",title:"Show ep1",downloaded:true,translated:true,cues:1}])', sandbox);
  assert(items.innerHTML.includes('&token=' + token));
  assert(items.innerHTML.includes('>Ngữ cảnh</button>'));
  assert(items.innerHTML.includes("title='Ngữ cảnh dịch'"));
  assert(items.innerHTML.includes("aria-expanded='true'"));
  assert(!items.innerHTML.includes("class='episodeList' hidden"));
  vm.runInContext('episodeData=[{tvid:"101",albumId:"9",title:"Show ep1"}]; toggleAlbum("iqiyi:id:9")', sandbox);
  assert(items.innerHTML.includes("aria-expanded='false'"));
  assert(items.innerHTML.includes("class='episodeList' hidden"));
  vm.runInContext('albumLists={"9":{stage:"loading"}};render(episodeData)', sandbox);
  assert(items.innerHTML.includes('Đang lấy toàn bộ danh sách tập'));
  vm.runInContext('albumLists={"9":{stage:"error",message:"<offline>"}};render(episodeData)', sandbox);
  assert(items.innerHTML.includes('&lt;offline&gt;'));
  vm.runInContext('episodeData=[{tvid:"101",albumId:"9",title:"Show ep1",order:1},{tvid:"102",albumId:"9",title:"Show ep2",order:2}];render(episodeData)', sandbox);
  assert.equal((items.innerHTML.match(/class='episodeChip /g)||[]).length, 2);
  assert.equal((items.innerHTML.match(/class='episodeRow'/g)||[]).length, 1);
  vm.runInContext('selectEpisode("iqiyi:id:9","102")', sandbox);
  assert(items.innerHTML.includes("id='panel-102'"));
  assert(!items.innerHTML.includes("id='panel-101'"));
  vm.runInContext('render([...episodeData,{tvid:"103",albumId:"10",title:"New ep1"}])', sandbox);
  assert.equal((items.innerHTML.match(/aria-expanded='false'/g)||[]).length, 1);
  assert.equal((items.innerHTML.match(/aria-expanded='true'/g)||[]).length, 1);
  await vm.runInContext('retryDownload("102")', sandbox);
  assert(calls.some(call => call.url === '/api/download' && JSON.parse(call.options.body).tvid === '102'));
  const key = vm.runInContext(`albumKey({tvid:'101',title:"O'Reilly"})`, sandbox);
  assert(!key.includes("'"));
  vm.runInContext('render([{tvid:"101",albumId:"9",title:"Show ep1",downloaded:true,cues:2,translatedCount:2,agentPending:true,partial:true}])', sandbox);
  assert(items.innerHTML.includes('Dịch tiếp'));
  assert(items.innerHTML.includes('Dịch một phần 2/2'));
  assert.equal(vm.runInContext('episodeState({translated:true,progress:{stage:"translating",phase:"review"}}).label', sandbox), 'Đang dịch');
  console.log('PASS: manager authenticates API calls and SRT downloads; quoted titles remain safe');
}

async function playerSessionSync() {
  let info = {authcookie:'private-session',uid:'123',vip_types:'1,4'}, tick, now=100000;
  const calls=[];
  const window={__iqiyiViToken:token,location:{pathname:'/index.html',hostname:'localwebapp.iqiyi.com'},
    QySdk:{Account:{getLoginInfo(){return {cache:info}}},AppService:{getSystemInfo(){return {cache:{deviceId:'device'}}}}},
    setInterval(callback){tick=callback},fetch:async(url,options)=>{calls.push({url,options});return reply()}};
  vm.runInNewContext(source,{window,Map,Set,Promise,Date:{now:()=>now}});
  await flush();
  assert.equal(calls.length,1);
  assert.equal(calls[0].url,'http://127.0.0.1:18766/api/session');
  assert.equal(calls[0].options.headers['X-Iqiyi-Token'],token);
  assert.equal(JSON.parse(calls[0].options.body).authcookie,'private-session');
  assert.deepEqual(JSON.parse(calls[0].options.body).vipTypes,['1','4']);
  tick();await flush();assert.equal(calls.length,1);
  now+=30001;tick();await flush();assert.equal(calls.length,2);
  info={authcookie:'',uid:'',is_login:false};tick();await flush();
  assert.equal(JSON.parse(calls.at(-1).options.body).authcookie,'');
  assert.equal(window.__iqiyiSubtitleEngine,undefined);
  console.log('PASS: home page syncs SDK login, heartbeats and logout without opening an episode');
}

function subtitleStyleLifecycle() {
  let ready, style, additions = 0;
  const head = {appendChild(node) { style = node; node.parentNode = head; additions++; }};
  const document = {documentElement: null, head, getElementById() { return style; },
    createElement() { return {}; }, querySelectorAll() { return []; },
    addEventListener(event, callback) { if (event === 'DOMContentLoaded') ready = callback; }};
  const window = {document, location: {pathname: '/player.html', hostname: 'localwebapp.iqiyi.com'}};
  const sandbox = vm.createContext({window});
  vm.runInContext(source, sandbox);
  assert.equal(style, undefined);
  document.documentElement = {};
  ready();
  assert.equal(additions, 1);
  style.textContent = 'stale';
  vm.runInContext(source, sandbox);
  assert.equal(additions, 1);
  assert.notEqual(style.textContent, 'stale');
  console.log('PASS: early player injection waits for the DOM and refreshes its single stylesheet on reinjection');
}

function subtitleOverlayIsNotUiText() {
  const text = {nodeType: 3, nodeValue: '你好\n第二行', isConnected: true};
  const element = {nodeType: 1, tagName: 'DIV', id: 'youku-vi-subtitle', className: '',
    childNodes: [text], firstChild: text, childElementCount: 0,
    get textContent() { return text.nodeValue; }, getAttribute() { return null; }};
  const window = {__iqiyiViDict: {'你好': 'Xin chào'}};
  const sandbox = {window, location: {pathname: '/video'}, document: {body: {}, documentElement: element,
    getElementById() { return {remove() {}}; }, querySelector() { return null; }, querySelectorAll() { return []; }},
    localStorage: {getItem() { return null; }}, setInterval() {}, clearInterval() {},
    MutationObserver: class { observe() {} disconnect() {} }};
  const engine = fs.readFileSync(require('node:path').join(__dirname, 'ui-engine.js'), 'utf8')
    .replace('subtitleContainer|caption-main', 'subtitleContainer|caption-main|kui-subtitle|youku-vi-subtitle');
  vm.runInNewContext(engine, sandbox);
  assert.equal(text.nodeValue, '你好\n第二行');
  console.log('PASS: UI translation leaves the subtitle overlay and its line breaks untouched');
}

(async () => {
  await tracksAndAuth();
  await retryRegistration();
  await captureWaitsForRegistrationAndUsesPreferredTrack();
  await staleUiTranslation();
  uiCacheAndDictionaryReload();
  await managerClientWiring();
  await playerSessionSync();
  subtitleStyleLifecycle();
  subtitleOverlayIsNotUiText();
})().catch(error => { console.error(error); process.exitCode = 1; });
