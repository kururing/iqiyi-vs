/* Run: node tests/check_extension_standalone.cjs */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const listeners = [];
let calls = [], upstream;
const context = vm.createContext({URL, URLSearchParams, AbortController, TextDecoder, setTimeout, clearTimeout,
  crypto: require('node:crypto').webcrypto,
  chrome: {runtime: {id: 'test-extension', onMessage: {addListener: fn => listeners.push(fn)},
    getURL: name => 'chrome-extension://test-extension/' + name}},
  fetch: async (input, options) => {
    const url = new URL(input);
    if (url.hostname === 'pcw-api.iq.com') assert.equal(url.searchParams.get('modeCode'), 'vn');
    calls.push(url.href);
    assert.equal(url.protocol, 'https:', 'Public routes must not read config or call localhost');
    assert.equal(options.credentials, 'omit');
    if (options.signal?.aborted) throw options.signal.reason;
    const value = await upstream(url, options);
    const raw = value instanceof Uint8Array ? value : new TextEncoder().encode(JSON.stringify(value));
    return {ok: true, arrayBuffer: async () => raw.buffer.slice(raw.byteOffset, raw.byteOffset + raw.byteLength)};
  }});
for (const file of ['public-api-worker.js', 'local-api-worker.js']) {
  vm.runInContext(fs.readFileSync(path.join(root, 'ext', file), 'utf8'), context);
}
const send = (pathname, body, signal) => context.localPlayerRequest({
  path: pathname, method: body === undefined ? 'GET' : 'POST', body: body === undefined ? undefined : JSON.stringify(body)
}, signal);
const read = result => JSON.parse(result.body);

(async () => {
  assert.equal(read(await send('/api/audio-frame')).url, 'chrome-extension://test-extension/audio-player.html');
  assert.equal(calls.length, 0, 'Audio frame discovery uses the extension URL without reading credentials or fetching media');
  upstream = async (url, options) => {
    assert.equal(url.hostname, 'clients5.google.com');
    assert.deepEqual(new URLSearchParams(options.body).getAll('q'), ['播放', '暂停']);
    return ['Phát', 'Tạm dừng'];
  };
  assert.deepEqual(read(await send('/api/localize-remaining', {texts: ['播放', '暂停']})), {translations: ['Phát', 'Tạm dừng']});
  await send('/api/localize-remaining', {texts: ['播放', '暂停']});
  assert.equal(calls.length, 1, 'Successful requests are cached');
  const labels = Array.from({length:8},(_,i)=>'提示文案'+i);
  upstream = async (url,options) => {
    assert.deepEqual(new URLSearchParams(options.body).getAll('q'),labels);
    return labels.map((_,i)=>'Nhãn '+i);
  };
  assert.equal(read(await send('/api/localize-remaining',{texts:labels})).translations.length,8);
  await assert.rejects(send('/api/localize-remaining',{texts:[...labels,'超出限制']}),/không hợp lệ/);
  await assert.rejects(send('/api/localize-remaining', {texts: []}), /không hợp lệ/);
  upstream = async () => ['仍然中文'];
  await assert.rejects(send('/api/localize-remaining', {texts: ['设置']}), /chưa trả đủ/);
  upstream = async () => ['Cài đặt'];
  assert.deepEqual(read(await send('/api/localize-remaining', {texts: ['设置']})), {translations: ['Cài đặt']});
  upstream = async () => { throw Error('offline'); };
  await assert.rejects(send('/api/localize-remaining', {texts: ['重试']}), /offline/);
  for (const raw of [new Uint8Array([0x5b, 0x22, 0xe7]), new TextEncoder().encode('["cut')]) {
    upstream = async () => raw;
    await assert.rejects(send('/api/localize-remaining', {texts: ['重试']}), /bị thiếu hoặc không hợp lệ/);
  }
  upstream = async () => ['Thử lại'];
  assert.deepEqual(read(await send('/api/localize-remaining', {texts: ['重试']})), {translations: ['Thử lại']});

  const domestic = {albumName: '测试剧', year: '2024', channelId: 2};
  const row = {qipuId: '12345678', name: '测试剧', publishTime: '2024-01-01', chnId: 2, type: 1};
  const id = '987654321';
  const encoded = (BigInt(id) ^ 0x75706971676cn).toString(36);
  upstream = async url => {
    if (url.hostname === 'pcw-api.iqiyi.com') {
      assert.ok(url.pathname.endsWith('/' + id), 'Page IDs use precise base36 decoding');
      return {code: 'A00000', data: domestic};
    }
    if (url.pathname === '/api/search2') return {code: 0, data: {epg: [row,
      {...row, qipuId: '22222222', publishTime: '2025-01-01'}, {...row, qipuId: '33333333', chnId: 1}]}};
    assert.equal(url.searchParams.get('langCode'), 'vi_vn');
    return {code: 0, data: {qipuId: row.qipuId, albumName: 'Phim thử', matchedLang: 15}};
  };
  assert.deepEqual(read(await send('/api/international-title?id=' + encoded)), {
    title: 'Phim thử', sourceTitle: domestic.albumName, globalAlbumId: row.qipuId
  });
  upstream = async () => { throw Error('Alias should be resolved from verified title'); };
  assert.equal(read(await send('/api/international-search?q=phim%20thu')).query, domestic.albumName);
  assert.equal(read(await send('/api/international-search?q=phim%20thu')).title, 'Phim thử');
  upstream = async url => url.hostname === 'pcw-api.iqiyi.com' ? {code: 'A00000', data: domestic} :
    {code: 0, data: {epg: [row, {...row, qipuId: '44444444'}]}};
  assert.equal(read(await send('/api/international-title?id=987654322')).title, '', 'Ambiguous editions stay untranslated');

  upstream = async url => {
    if (url.hostname === 'pcw-api.iqiyi.com') return {code: 'A00000',
      data: {albumId: '6582272134154501', name: '黑岛监狱', year: '2026', channelId: 2}};
    assert.equal(url.searchParams.get('modeCode'), 'vn');
    if (url.pathname === '/api/search2') return {code: 0, data: {epg: []}};
    assert.ok(url.pathname.endsWith('/6582272134154501'));
    return {code: 0, data: {qipuId: '6582272134154501', publishTime: '20260923', chnId: 2,
      name: url.searchParams.get('langCode') === 'vi_vn' ? 'Nhà Tù Hắc Đảo' : '黑岛监狱', matchedLang: 15}};
  };
  assert.deepEqual(read(await send('/api/international-title?id=6582272134154501')), {
    title: 'Nhà Tù Hắc Đảo', sourceTitle: '黑岛监狱', globalAlbumId: '6582272134154501'
  }, 'Any unindexed album can resolve through its own verified catalog ID');
  for (const mutation of [{qipuId: '99999999'}, {name: '另一部剧'}, {publishTime: '20240101'}, {chnId: 4}]) {
    upstream = async url => url.hostname === 'pcw-api.iqiyi.com' ?
      {code: 'A00000', data: {name: '测试剧', year: '2025', channelId: 2}} :
      url.pathname === '/api/search2' ? {code: 0, data: {epg: []}} :
      {code: 0, data: {qipuId: '66666666', name: '测试剧', publishTime: '20250101', chnId: 2, ...mutation}};
    assert.equal((await context.publicMovieTitle('66666666')).title, '', 'Direct lookup must verify identity');
  }

  const titleOnlyRow = {type: 1, qipuId: '87654321', name: '测试仅标题剧', chnId: 2, publishTime: '20250101'};
  function nameCatalog(extra = [], original = {}, localized = {}) {
    return async url => url.pathname === '/api/search2' ? {code: 0, data: {epg: [titleOnlyRow, ...extra]}} :
      {code: 0, data: {...titleOnlyRow, ...(url.searchParams.get('langCode') === 'vi_vn' ?
        {name: 'Phim từ tên gốc', matchedLang: 15, ...localized} : original)}};
  }
  upstream = nameCatalog();
  assert.deepEqual(read(await send('/api/international-title?name=' + encodeURIComponent(titleOnlyRow.name))), {
    title: 'Phim từ tên gốc', sourceTitle: titleOnlyRow.name, globalAlbumId: titleOnlyRow.qipuId
  });
  upstream = nameCatalog([{...titleOnlyRow, qipuId: '76543210'}]);
  assert.equal((await context.publicMovieTitleByName(titleOnlyRow.name)).title, '', 'A title-only card cannot choose between two editions');
  for (const mutation of [{qipuId: '99999999'}, {name: '另一部剧'}, {chnId: 4}, {publishTime: '20240101'}]) {
    upstream = nameCatalog([], mutation);
    assert.equal((await context.publicMovieTitleByName(titleOnlyRow.name)).title, '', 'Full title-only metadata must match');
  }
  upstream = nameCatalog([], {}, {matchedLang: 1});
  assert.equal((await context.publicMovieTitleByName(titleOnlyRow.name)).title, '');
  await assert.rejects(context.publicMovieTitleByName('English title'), /không hợp lệ/);

  upstream = async url => ({code: 0, data: {starsInfo: url.searchParams.get('langCode') === 'vi_vn' ?
    {qipuId: '123', name: 'Diễn viên thử'} : {qipuId: '124', name: '演员甲'}}});
  assert.equal(read(await send('/api/international-actor?name=' + encodeURIComponent('演员甲'))).name, '', 'Person IDs must match');
  upstream = async url => ({code: 0, data: {starsInfo: url.searchParams.get('langCode') === 'vi_vn' ?
    {qipuId: '125', name: 'Diễn viên khác'} : {qipuId: '125', name: '演员乙'}}});
  assert.equal(read(await send('/api/international-actor?name=' + encodeURIComponent('演员乙'))).name, 'Diễn viên khác');

  upstream = async url => url.pathname === '/api/search2' ?
    {code: 0, data: {epg: [{type: 1, qipuId: '55555555', name: 'Tên phim mới'}]}} :
    {code: 0, data: {qipuId: '55555555', albumName: '新剧'}};
  assert.equal(read(await send('/api/international-search?q=' + encodeURIComponent('ten phim moi'))).query, '新剧');
  assert.equal(read(await send('/api/international-search?q=' + encodeURIComponent('ten phim moi'))).title, 'Tên phim mới');
  const typo = read(await send('/api/international-search?q=' + encodeURIComponent('ten phin moi')));
  assert.equal(typo.query, 'ten phin moi');
  assert.equal(typo.suggestions[0].query, '新剧', 'Typos offer a verified choice instead of silently replacing the query');
  await assert.rejects(send('//evil.test/api/international-title?id=12345678'), /không được phép/);
  await assert.rejects(send('/api/localize-remaining'), /không được phép/);
  const controller = new AbortController();
  controller.abort(Error('cancelled'));
  await assert.rejects(send('/api/localize-remaining', {texts: ['取消']}, controller.signal), /cancelled/);
  let replied = false;
  assert.equal(listeners[0]({type: 'iqiyi-local-api', path: '/api/international-search?q=test'},
    {id: 'other-extension', url: 'https://www.iqiyi.com/'}, () => { replied = true; }), undefined);
  assert.equal(replied, false, 'Untrusted senders cannot access public routes');
  const reply = await new Promise(resolve => listeners[0]({type: 'iqiyi-local-api',
    path: '/api/localize-remaining', method: 'POST', body: JSON.stringify({texts: ['播放', '暂停']})},
    {id: 'test-extension', url: 'https://www.iqiyi.com/', tab: {id: 1}, frameId: 0}, resolve));
  assert.deepEqual(read(reply).translations, ['Phát', 'Tạm dừng']);
  console.log('Standalone extension checks passed: no app/config, translation, metadata identity, search, cache, cancellation and sender validation.');
})().catch(error => { console.error(error); process.exitCode = 1; });
