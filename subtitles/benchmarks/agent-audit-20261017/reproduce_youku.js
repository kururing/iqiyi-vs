// Offline browser probes: simulated clock, DOM, fetch and timers only.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../../../youku-subtitle.js'), 'utf8');
const flush = () => new Promise(resolve => setImmediate(resolve));

function player(fetch) {
  let overlay;
  let now = 10000;
  const intervals = new Map(), timeouts = new Map();
  let sequence = 0;
  const video = {currentTime: 1.5, textTracks: [{activeCues: [], cues: []}]};
  const location = {href: 'client://iku.youku.com/video?vid=first'};
  const document = {
    title: 'Audit ep1',
    body: {appendChild(node) { node.isConnected = true; overlay = node; }},
    createElement() { return {style: {}, setAttribute() {}, remove() { this.isConnected = false; }}; },
    querySelector(selector) { return selector === 'video' ? video : null; },
    querySelectorAll(selector) { return selector === 'video' ? [video] : []; },
  };
  const localStorage = {getItem() { return '{}'; }, setItem() {}};
  const window = {__youkuViToken: 'offline', fetch, localStorage};
  const sandbox = vm.createContext({window, document, location, URL, localStorage,
    innerHeight: 900, Date: {now: () => now}, Promise,
    setTimeout(callback) { const id = ++sequence; timeouts.set(id, callback); return id; },
    clearTimeout(id) { timeouts.delete(id); },
    setInterval(callback) { const id = ++sequence; intervals.set(id, callback); return id; },
    clearInterval(id) { intervals.delete(id); }});
  vm.runInContext(source, sandbox);
  return {video, location, window, get overlay() { return overlay; },
    tick() { for (const callback of [...intervals.values()]) callback(); },
    advance(ms) { now += ms; },
    runTimeouts() { const callbacks = [...timeouts.values()]; timeouts.clear(); callbacks.forEach(cb => cb()); }};
}

async function main() {
  let resolveGoogle;
  const late = player(url => {
    if (url.startsWith('https://clients5.google.com/')) return new Promise(resolve => { resolveGoogle = resolve; });
    if (url.includes('/api/file?')) return Promise.resolve({ok: true,
      text: async () => '1\n00:00:01,000 --> 00:00:02,000\nBản agent đã soát\n'});
    return Promise.resolve({ok: true, json: async () => ({})});
  });
  late.video.textTracks[0].activeCues = [{text: '你好', startTime: 1, endTime: 2}];
  late.tick(); await flush(); late.tick();
  assert.equal(late.overlay.textContent, 'Bản agent đã soát');
  resolveGoogle({ok: true, json: async () => ['Bản Google đến muộn']});
  await flush();
  assert.equal(late.overlay.textContent, 'Bản Google đến muộn');
  const overwritten = late.overlay.textContent;

  const payloads = [];
  const mixed = player(async (url, init) => {
    if (url.endsWith('/api/capture')) payloads.push(JSON.parse(init.body));
    return {ok: true, json: async () => ({}), text: async () => ''};
  });
  mixed.video.textTracks[0].cues = [
    {text: '你好', startTime: 1, endTime: 2},
    {text: 'Hello!', startTime: 2, endTime: 3},
    {text: '♪', startTime: 3, endTime: 4},
    {text: '...', startTime: 4, endTime: 5},
  ];
  mixed.tick(); mixed.runTimeouts(); await flush();
  assert.equal(payloads.length, 1);
  assert(payloads[0].raw.includes('你好'));
  assert(!payloads[0].raw.includes('Hello!'));
  assert(!payloads[0].raw.includes('♪'));
  assert(!payloads[0].raw.includes('...'));

  const uploads = [];
  const switched = player(async (url, init) => {
    if (url.endsWith('/api/capture')) uploads.push(JSON.parse(init.body));
    return {ok: true, json: async () => ({}), text: async () => ''};
  });
  switched.video.textTracks[0].cues = Array.from({length: 1000}, (_, i) => ({
    text: '句' + i, startTime: i * 3, endTime: i * 3 + 2}));
  switched.tick(); await flush();
  switched.location.href = 'client://iku.youku.com/video?vid=second';
  switched.video.textTracks[0].cues = [];
  switched.advance(100); switched.tick(); await flush();
  switched.runTimeouts(); await flush();
  const capturedCount = uploads.filter(p => p.tvid === 'yk-first')
    .reduce((sum, p) => sum + (p.raw.match(/ --> /g) || []).length, 0);
  assert.equal(capturedCount, 400);

  console.log(JSON.stringify({
    lateGoogle: {expected: 'Bản agent đã soát', actual: overwritten},
    mixedTrack: {inputCues: 4, uploadedCues: (payloads[0].raw.match(/ --> /g) || []).length},
    switchBeforeDrain: {inputCues: 1000, uploadedCues: capturedCount, lostCues: 1000 - capturedCount},
  }, null, 2));
}

main().catch(error => { console.error(error); process.exitCode = 1; });
