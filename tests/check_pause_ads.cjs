/* Run: node tests/check_pause_ads.cjs */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../ext/sub-hook.js'), 'utf8');
let requests = 0, aborted = 0, cleared = 0, definition = 0;
class Video {
  constructor() { this.state = 'paused'; this.time = 123; }
  requestPauseAd() { requests++; }
  tryToStopPauseAd() { aborted++; }
  requestDefinitionAd() { definition++; }
}
const first = new Video();
const controller = {sdk: null, initVV() {}, getAdnAds() {}};
function clear(...placements) {
  /* Clear ad data */
  assert.deepEqual(placements, ['ad_pause', 'ad_pause_max']);
  cleared++;
}
function runtime(id) { return id === 'controller' ? {controller} : {clear}; }
runtime.m = {controller() { /* _videoAdHandler getAdnAds */ },
  cleanup() { /* Clear ad data */ }};
const context = vm.createContext({officialRuntimeRequire: null});
vm.runInContext(source.slice(source.indexOf('    var pauseAdController ='),
  source.indexOf('    function installOfficialSubtitleName()')), context);
context.disablePauseAds();
context.officialRuntimeRequire = runtime;
context.disablePauseAds();  // SDK can become ready after the UI.
controller.sdk = {currentVV:first};
context.disablePauseAds();
first.requestPauseAd();
assert.equal(requests, 0);
assert.equal(aborted, 1);
assert.equal(cleared, 1);
assert.equal(first.state, 'paused');
assert.equal(first.time, 123);
context.disablePauseAds();
assert.equal(cleared, 1, 'Do not repeatedly reset the player UI');
controller.sdk.currentVV = new Video();
controller.sdk.currentVV.requestPauseAd();
context.disablePauseAds();
assert.equal(requests, 0, 'Next episodes inherit pause suppression');
assert.equal(cleared, 2);
first.requestDefinitionAd();
assert.equal(definition, 1, 'Other placements retain their original handlers');
assert.equal(controller.sdk.currentVV.state, 'paused');
console.log('PASS: pause ads suppressed, existing placements cleared once, future episodes covered, playback state unchanged.');
