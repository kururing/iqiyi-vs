const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync(require('node:path').join(__dirname, 'youku-subtitle.js'), 'utf8');
const flush = () => new Promise(resolve => setImmediate(resolve));

function player({token = '', fetch, cached = {}, native = false} = {}) {
  let now = 10000, overlay, nextTimer = 0;
  const timers = new Map();
  const video = {currentTime: 1.5, textTracks: [{activeCues: [], cues: []}]};
  const location = {href: 'client://iku.youku.com/video?vid=first'};
  const document = {
    title: 'Youku test episode',
    body: {appendChild(node) { node.isConnected = true; overlay = node; }},
    createElement() { return {style: {}, setAttribute() {}, remove() { this.isConnected = false; }}; },
    querySelector(selector) { return selector === 'video' && !native ? video : null; },
    querySelectorAll(selector) { return selector === 'video' && !native ? [video] : []; },
  };
  const localStorage = {getItem() { return JSON.stringify(cached); }, setItem() {}};
  const window = {__youkuViToken: token, fetch, localStorage};
  if (native) window.videoPlayer = {getCurrentTime: () => video.currentTime,
    getPlayerInfo: () => ({vidEncoded: 'native-first', showEncodedId: 'show'})};
  const sandbox = vm.createContext({window, document, location, URL, localStorage, innerHeight: 900,
    Date: {now: () => now}, setTimeout, clearTimeout, Promise,
    setInterval(callback) { const id = ++nextTimer; timers.set(id, callback); return id; },
    clearInterval(id) { timers.delete(id); }});
  const load = () => vm.runInContext(source, sandbox);
  load();
  return {window, video, location, load, timers, get overlay() { return overlay; },
    tick() { for (const callback of [...timers.values()]) callback(); },
    advance(ms) { now += ms; }};
}

async function main() {
  const chinese = '你好，欢迎回来', vietnamese = 'Xin chào, mừng bạn quay lại';
  const cached = player({cached: {[chinese]: vietnamese}});
  cached.video.textTracks[0].activeCues = [{text: chinese, startTime: 1, endTime: 2}];
  cached.tick();
  assert.equal(cached.overlay.textContent, vietnamese);
  assert.equal(cached.overlay.style.display, 'block');
  assert(cached.overlay.style.cssText.includes('font:700'));
  cached.video.textTracks[0].activeCues = [];
  cached.advance(800); cached.tick();
  assert.equal(cached.overlay.style.display, 'none');
  console.log('PASS: cached live captions use the bold subtitle style and clear after the cue');

  const calls = [];
  const managed = player({token: 'offline', native: true, fetch: async url => {
    calls.push(url);
    return {ok: true, json: async () => ({}), text: async () => '1\n00:00:01,000 --> 00:00:02,000\nTiếng Việt có dấu\nDòng thứ hai\n'};
  }});
  managed.location.href = 'client://iku.youku.com/video';
  managed.video.textTracks[0].cues = [{text: vietnamese, startTime: 1, endTime: 2}];
  managed.tick(); await flush(); managed.tick();
  assert.equal(managed.overlay.textContent, 'Tiếng Việt có dấu\nDòng thứ hai');
  assert.equal(managed.window.__youkuViSubtitleStatus().managed, 1);
  assert(calls.some(url => url.includes('/api/file?tvid=yk-native-first')));
  assert.equal(managed.window.__youkuViSubtitleStatus().captured, 0);
  assert(!calls.some(url => url.endsWith('/api/capture')));
  managed.video.currentTime = 2; managed.tick();
  assert.equal(managed.overlay.style.display, 'none');
  console.log('PASS: native Youku playback clock displays Vietnamese SRT, preserves both lines and clears exactly at cue end');
  managed.location.href = 'client://iku.youku.com/ku/webhome';
  const before = calls.length;
  managed.advance(5000); managed.tick();
  assert.equal(managed.overlay.style.display, 'none');
  assert.equal(calls.length, before);
  console.log('PASS: the home page does not register fake videos or translate recommendation cards as captions');

  const pending = [];
  const switched = player({token: 'offline', fetch: url => url.includes('/api/file?')
    ? new Promise(resolve => pending.push(resolve))
    : Promise.resolve({ok: true, json: async () => ({})})});
  switched.tick(); switched.location.href = 'client://iku.youku.com/video?vid=second';
  switched.advance(5000); switched.tick();
  pending[0]({ok: true, text: async () => '1\n00:00:01,000 --> 00:00:02,000\nTập cũ\n'});
  await flush(); switched.tick();
  assert.equal(switched.window.__youkuViSubtitleStatus().managed, 0);
  pending[1]({ok: true, text: async () => '1\n00:00:01,000 --> 00:00:02,000\nTập mới\n'});
  await flush(); switched.tick();
  assert.equal(switched.overlay.textContent, 'Tập mới');
  console.log('PASS: a late subtitle download cannot overwrite the next episode');

  cached.load();
  assert.equal(cached.timers.size, 1);
  cached.window.__youkuViSubtitleVersion = 1;
  cached.load();
  assert.equal(cached.timers.size, 1);
  cached.window.__youkuViSubtitleStop();
  assert.equal(cached.timers.size, 0);
  assert.equal(cached.overlay.isConnected, false);
  console.log('PASS: reinjection refreshes the style and upgrades without duplicate timers or overlays');
}
main().catch(error => { console.error(error); process.exitCode = 1; });
