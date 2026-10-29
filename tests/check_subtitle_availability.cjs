/* Run: node tests/check_subtitle_availability.cjs */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../ext/sub-hook.js'), 'utf8');
const start = source.indexOf('    function retryLocalSubtitle(');
const end = source.indexOf('    function applyLocalSubtitleState(', start);
const tvid = '12345678', official = 90023, ai = 90024;
let selected = official, calls = [];
const view = {model: {data: {1: {[official]: []}}}, captionLids: new Map([[1, official]])};
const control = {subtitleSdk: {sdk: {view}},
  _getSubTitleList: () => [{lid: selected, type: 1, status: true}],
  openSubTitle: (type, lid) => {
    assert.equal(view.model.data[1][lid], undefined, 'Clear the empty SDK cache before reloading');
    calls.push(lid);
    view.model.data[1][lid] = [{st: 1, et: 2, sub: 'Ready'}];
    view.captionLids.set(1, lid);
  }};
const context = vm.createContext({officialNativeControl: control, AI_LID: ai, currentSubtitleTvid: () => tvid});
vm.runInContext(source.slice(start, end), context);
context.retryLocalSubtitle(tvid, official, false);
assert.equal(calls.length, 0, 'An unavailable track stays unavailable');
context.retryLocalSubtitle(tvid, official, true);
assert.deepEqual(calls, [official], 'A ready official track reloads its empty preload');
context.retryLocalSubtitle(tvid, official, true);
assert.equal(calls.length, 1, 'A loaded, active track is left playing');
selected = ai;
view.model.data[1][ai] = [];
view.__iqiyiAiVersion = 'job1';
context.retryLocalSubtitle(tvid, ai, true, 'job1');
assert.deepEqual(calls, [official, ai], 'AI placeholders also reload for the same job');
view.__iqiyiOfficialRetryAt = 0;
context.retryLocalSubtitle(tvid, ai, true, 'job2');
assert.deepEqual(calls, [official, ai, ai], 'A new AI version replaces the old cues');
context.retryLocalSubtitle('87654321', ai, true, 'job3');
assert.equal(calls.length, 3, 'Responses for another episode do not change the player');
console.log('Subtitle availability checks passed: waiting, ready, empty cache, AI updates and episode changes.');
