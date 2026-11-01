/* Run: node tests/check_native_watermark.cjs */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../ext/sub-hook.js'), 'utf8');
const code = source.slice(source.indexOf('    var nativeWatermarkHidden ='),
  source.indexOf('    function installOfficialSubtitleName()'));
let visible = true, refreshes = 0, inserts = 0;
class Watermark {
  addWaterMark() { visible = true; inserts++; }
  refreshWaterMark() { visible = true; }
  removeWaterMark() { visible = false; }
}
const watermark = new Watermark();
class NativeWatermark {
  addWaterMark() { visible = true; inserts++; }
  refreshWaterMark() { visible = true; }
  removeWaterMark() { visible = false; }
}
const nativeWatermark = new NativeWatermark();
const state = {getProp: key => key === 'playState' ? 'play' : undefined,
  forceUpdateProp(key) { assert.equal(key, 'playState'); refreshes++; nativeWatermark.refreshWaterMark(); }};
function runtime(id) { return id === 'logo' ? {Watermark} : id === 'nativeLogo' ? {NativeWatermark} : {state}; }
runtime.m = {logo() { /* watermarkList nodeHandlerVideoCover */ },
  nativeLogo() { /* watermarkList nodeHandlerVideoCover */ },
  player() { /* xplayerProgressTouch */ }};
const context = vm.createContext({officialRuntimeRequire: null});
vm.runInContext(code, context);
context.hideNativePlayerWatermark();
assert.equal(visible, true, 'Wait for the player runtime');
context.officialRuntimeRequire = runtime;
context.hideNativePlayerWatermark();
assert.equal(visible, false, 'Remove the logo already on screen');
watermark.addWaterMark();
watermark.refreshWaterMark();
nativeWatermark.addWaterMark();
nativeWatermark.refreshWaterMark();
assert.equal(visible, false, 'Keep the logo hidden when the player refreshes');
assert.equal(inserts, 0);
context.hideNativePlayerWatermark();
assert.equal(refreshes, 1, 'Install once without repeatedly refreshing playback state');
console.log('Native watermark checks passed.');
