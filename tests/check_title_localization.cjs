/* Run: node tests/check_title_localization.cjs */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../ext/content.js'), 'utf8');
const fixedCopy = JSON.parse(source.match(/var FIXED_COPY = (\{[\s\S]*?\});/)[1]);
const location = {href: 'https://www.iqiyi.com/u/record', pathname: '/u/record'};
function element(className = '', parentElement = null, attrs = {}, tagName = 'P') {
  return {nodeType: 1, tagName, className, parentElement, isConnected: true,
    getAttribute: key => attrs[key] || null,
    setAttribute: (key, value) => { attrs[key] = value; },
    get textContent() { return this._text?.nodeValue || ''; },
    closest(selector) {
      for (let el = this; el; el = el.parentElement) {
        if (selector === '.search-board-item' && el.className === 'search-board-item') return el;
        if (selector === '#search .item-charactor .name' && el.className.trim() === 'name' && el.parentElement?.className === 'charactor-info') return el;
        if ([...selector.matchAll(/\[class\*="([^"]+)"\]/g)].some(match => el.className.includes(match[1]))) return el;
      }
      return null;
    },
    matches: () => false, getClientRects: () => [{}],
    getBoundingClientRect: () => ({top: 100, bottom: 120})};
}
const text = (value, parentElement) => {
  const node = {nodeType: 3, nodeValue: value, parentElement, isConnected: true};
  parentElement._text = node;
  parentElement.childNodes = [node];
  parentElement.firstChild = node;
  parentElement.childElementCount = 0;
  return node;
};
function documentTitle(value) {
  const title = element('', null, {}, 'TITLE');
  title.childNodes = value ? [text(value, title)] : [];
  title.firstChild = title.childNodes[0] || null;
  Object.defineProperty(title, 'textContent', {get: () => title.childNodes.map(node => node.nodeValue).join('')});
  title.appendChild = node => {
    node.parentElement = title;
    title.childNodes.push(node);
    title.firstChild = title.childNodes[0];
  };
  return title;
}
function fixture(nodes, cache = [], fetcher = async () => ({translations: ['Quản lý']}), pageTitle = null) {
  const requests = [], metadata = [], pending = [];
  const context = vm.createContext({URL, URLSearchParams, AbortController, setTimeout, clearTimeout, console, location:{...location},
    atob: value => Buffer.from(value, 'base64').toString(),
    document: {body: {}, hidden: false, querySelector: selector => selector === 'title' ? pageTitle : null,
      createTextNode: value => ({nodeType:3, nodeValue:value, isConnected:true}), createTreeWalker: () => {
      let index = 0;
      return {nextNode: () => nodes[index++] || null};
    }},
    NodeFilter: {SHOW_ELEMENT: 1, SHOW_TEXT: 4},
    getComputedStyle: () => ({visibility: 'visible'}),
    window: {innerHeight: 900, __iqiyiViPublicApi: true, fetch: true,
      __iqiyiViLocalFetch: async (url, options) => {
        requests.push(JSON.parse(options.body).texts);
        const payload = await fetcher(JSON.parse(options.body).texts);
        return {ok: !payload.error, json: async () => payload};
      }},
    localStorage: {setItem() {}}, FIXED_COPY: fixedCopy, IS_RANKING_PAGE: false,
    machineBusy: false, IQCOM_METADATA_STOPPED: false, IQCOM_METADATA_FALLBACK: new WeakMap(),
    IQCOM_METADATA_CONTROLLERS: new Set(), MACHINE_COPY: new Map(cache), MACHINE_RENDERED: new WeakMap(), MACHINE_PENDING: new Set(), MACHINE_RETRIES:new Map(),
    MACHINE_WORKERS: [{busy: false, retryAt: 0, failures: 0}], SEARCH_TITLE_ALIASES: new Map(),
    machineTextKey: value => value.replace(/\s+/g, ' ').trim(), scheduleRemainingLocalization() {},
    setMetadataPending() {}, requestInternationalActor: () => false, searchKey: value => value,
    tr: value => ({'演员':'Diễn viên','电视剧':'Phim bộ','2026年':'Năm 2026'}[value] || value),
    requestIqcomMetadata: async route => {
      metadata.push(route);
      return {title: 'Đại Mộng Quy Ly', sourceTitle: '大梦归离'};
    },
    waitForIqcomMetadata: (node, field, key, load, apply) => pending.push(load().then(apply))});
  vm.runInContext(source.slice(source.indexOf('  function cjkCount('), source.indexOf('  function pumpIqcomMetadata(')) +
    source.slice(source.indexOf('  function requestInternationalTitle('), source.indexOf('  function trPatterns(')) +
    source.slice(source.indexOf('  function localizePageTitle('), source.indexOf('  function fitCompact(')) +
    source.slice(source.indexOf('  function protectMetadataNames('), source.indexOf('  window.__iqiyiVi = true;')), context);
  return {context, requests, metadata, pending};
}

(async () => {
  const encoded = Buffer.from('1234567890123456').toString('base64');
  const link = element('', null, {href: 'https://www.iqiyi.com/tvg/to_page_url?album_id=' + encodeURIComponent(encoded)}, 'A');
  const title = element('tilesItem_title_multi__Q4NjX tilesItem_title_multi_newmine__4yQ3H', link, {title: '大梦归离'});
  const name = text('大梦归离', title);
  const note = text('管理', element('tilesItem_note__JfQnC', title));
  const actor = text('演员甲', element('actor-name__test'));
  const f = fixture([title, name, note, actor], [['大梦归离', 'Giấc mơ lớn trở lại'], ['演员甲', 'Diễn viên máy']]);
  assert.equal(f.context.isMovieTitleNode(name), true);
  assert.equal(f.context.isMovieTitleNode(title), true, 'Title attributes must also be protected');
  assert.equal(f.context.isMovieTitleNode(note), false, 'Inline updates are UI, not part of the film name');
  assert.equal(f.context.findInternationalTitleId(name), '1234567890123456');
  assert.equal(f.context.isMovieTitleNode(text('已看42%', element('tilesItem_desc_watch__test', title))), false);
  assert.equal(f.context.isMovieTitleNode(text('菜单', element('tilesItem_titles__R5qmR'))), false, 'Do not treat the entire metadata container as a title');
  await f.context.localizeRemaining();
  assert.deepEqual(f.requests.flat(), ['管理'], 'Only UI enters the machine translation request');
  assert.equal(name.nodeValue, '大梦归离', 'Persisted machine cache cannot overwrite a film title');
  assert.equal(title.getAttribute('title'), '大梦归离');
  assert.equal(actor.nodeValue, '演员甲', 'Actor names are protected from the same fallback');
  assert.equal(note.nodeValue, 'Quản lý');

  const shortLabels = Array.from({length:12},(_,i)=>text('提示文案'+i,element('ui-label')));
  const throughput = fixture(shortLabels,[],async()=>({translations:throughput.requests.at(-1).map((_,i)=>'Nhãn '+i)}));
  await throughput.context.localizeRemaining();
  assert.equal(throughput.requests[0].length,8,'Translate eight short labels per request instead of four');
  const above = text('上方提示',element('ui-label'));
  above.parentElement.getBoundingClientRect=()=>({top:-200,bottom:-180});
  const onScreen = text('当前屏幕可见的提示文本',element('ui-label'));
  const viewport = fixture([above,onScreen],[],async()=>({translations:['Thông báo đang hiển thị']}));
  await viewport.context.localizeRemaining();
  assert.deepEqual(viewport.requests[0],['当前屏幕可见的提示文本'],'Visible labels take priority over text already scrolled above the viewport');

  const mixedSources = ['界面甲','错误项','界面乙','界面丙'];
  const mixedNodes = mixedSources.map(raw=>text(raw,element('ui-label')));
  const mixed = fixture(mixedNodes,[],async texts=>texts.includes('错误项')
    ? {error:'Dịch nhanh chưa trả đủ nội dung tiếng Việt; sẽ thử lại.'}
    : {translations:texts.map(raw=>'Nhãn '+mixedSources.indexOf(raw))});
  const warnings=[];
  mixed.context.console={warn:message=>warnings.push(message)};
  await mixed.context.localizeRemaining();
  assert.deepEqual(mixedNodes.map(node=>node.nodeValue),['Nhãn 0','错误项','Nhãn 2','Nhãn 3'],
    'One untranslated item must not block valid labels in its batch');
  assert.equal(mixed.context.MACHINE_COPY.has('错误项'),false,'Never cache the failed source as a successful translation');
  assert.equal(mixed.context.MACHINE_RETRIES.get('错误项').failures,1);
  assert.ok(mixed.context.MACHINE_RETRIES.get('错误项').retryAt>Date.now());
  assert.equal(warnings.length,0,'An isolated incomplete translation is handled without an extension error');
  const requestCount=mixed.requests.length;
  await mixed.context.localizeRemaining();
  assert.equal(mixed.requests.length,requestCount,'Wait before retrying the rejected label');
  const fresh = text('新增提示',element('ui-label'));
  mixedNodes.push(fresh);
  await mixed.context.localizeRemaining();
  assert.deepEqual(mixed.requests.at(-1),['新增提示'],'A rejected label does not delay new page text');
  mixed.context.MACHINE_RETRIES.get('错误项').retryAt=0;
  mixedNodes.push(text('另一个提示',element('ui-label')));
  await mixed.context.localizeRemaining();
  assert.deepEqual(mixed.requests.at(-1),['错误项'],'Retry failed labels individually instead of poisoning another batch');
  assert.equal(mixed.context.MACHINE_RETRIES.get('错误项').failures,2);

  const alignedSources=['菜单甲','菜单乙','菜单丙'];
  const alignedNodes=alignedSources.map(raw=>text(raw,element('ui-label')));
  const writes=[];
  for(const node of alignedNodes) {
    let value=node.nodeValue;
    Object.defineProperty(node,'nodeValue',{get:()=>value,set:next=>{writes.push(next);value=next;}});
  }
  const shortResponse=fixture(alignedNodes,[],async texts=>({translations:texts.length>1
    ? ['Sai vị trí'] : ['Mục '+alignedSources.indexOf(texts[0])]}));
  await shortResponse.context.localizeRemaining();
  assert.deepEqual(alignedNodes.map(node=>node.nodeValue),['Mục 0','Mục 1','Mục 2']);
  assert.ok(!writes.includes('Sai vị trí'),'Never assign a short response to guessed positions');
  const unchanged=text('原文未翻译',element('ui-label'));
  const untranslated=fixture([unchanged],[],async texts=>({translations:texts}));
  await untranslated.context.localizeRemaining();
  assert.equal(unchanged.nodeValue,'原文未翻译');
  assert.equal(untranslated.context.MACHINE_COPY.size,0);
  assert.ok(untranslated.context.MACHINE_RETRIES.has('原文未翻译'));
  const related = text('金莎', element('RelatedPeopleSection_name__l0ObA'));
  const avatar = element('info_starAvatarImg__gI5VD', null, {alt: '鞠婧祎'}, 'IMG');
  assert.equal(f.context.isActorNameNode(related), true);
  assert.equal(f.context.isActorNameNode(avatar), true);
  assert.equal(f.context.isActorNameNode(text('相关人物', element('RelatedPeopleSection_title__test'))), false);
  const people = fixture([related, avatar], [['金莎', 'Ferrero Rocher'], ['鞠婧祎', 'Tên dịch sai']]);
  await people.context.localizeRemaining();
  assert.equal(related.nodeValue, '金莎', 'Related people must never use machine-cached names');
  assert.equal(avatar.getAttribute('alt'), '鞠婧祎', 'Avatar alternative text follows actor metadata');
  assert.equal(people.requests.length, 0);

  const bioSource = '演员简介'.repeat(50);
  const bio = text(bioSource, element('aboutTa_descInner__R5Ll8'));
  const background = text('其他说明', element('ui-label'));
  const biography = fixture([background, bio], [], async () => ({translations: ['Tiểu sử diễn viên']}));
  await biography.context.localizeRemaining();
  assert.equal(biography.requests[0][0], bioSource,
    'The visible biography is translated before unrelated labels');
  assert.equal(bio.nodeValue, 'Tiểu sử diễn viên');
  const paragraph = text('《白月梵星》白鹿主演', element('aboutTa_descInner__test'));
  const prose = fixture([paragraph], [], async () => ({translations: [prose.requests[0][0].replace('主演', 'đóng vai chính')]}));
  await prose.context.localizeRemaining();
  assert.match(paragraph.nodeValue, /Bạch Nguyệt Phạn Tinh/);
  assert.match(paragraph.nodeValue, /Bạch Lộc/);
  assert.doesNotMatch(prose.requests[0][0], /白月梵星|白鹿/, 'Verified names are not sent to the machine translator');
  assert.match(prose.context.protectMetadataNames('《未收录剧》').text, /未收录剧/, 'Unknown names retain machine translation');
  await prose.context.localizeRemaining();
  assert.equal(prose.requests.length, 1, 'Translated prose must not trigger a translation loop');

  assert.equal(f.context.requestInternationalTitle(name, name.nodeValue), true);
  await Promise.all(f.pending);
  assert.equal(name.nodeValue, 'Đại Mộng Quy Ly', 'History titles use official metadata via their encoded album link');
  assert.equal(f.metadata[0], 'international-title?id=1234567890123456');
  const unknown = text('未收录新剧', element('tilesItem_title_multi__test'));
  f.context.requestInternationalTitle(unknown, unknown.nodeValue);
  assert.equal(unknown.nodeValue, '未收录新剧', 'Unmatched titles retain the source name');

  const missing = text('未收录影片', element('filmFeed_title__test'));
  const fallback = fixture([missing], [], async () => ({translations: ['Tên phim dịch máy']}));
  fallback.context.requestIqcomMetadata = async () => ({});
  fallback.context.requestInternationalTitle(missing, missing.nodeValue);
  await Promise.all(fallback.pending);
  await fallback.context.localizeRemaining();
  assert.equal(missing.nodeValue, 'Tên phim dịch máy', 'An official miss enables machine fallback');
  fallback.context.requestInternationalTitle(missing, missing.nodeValue);
  await Promise.all(fallback.pending);
  assert.equal(missing.nodeValue, 'Tên phim dịch máy', 'Repeated misses preserve the existing machine result');
  fallback.context.requestIqcomMetadata = async () => ({title: 'Tên chính thức', sourceTitle: '未收录影片'});
  fallback.context.requestInternationalTitle(missing, missing.nodeValue);
  await Promise.all(fallback.pending);
  assert.equal(missing.nodeValue, 'Tên chính thức', 'A later official result replaces the machine fallback');

  const shortSource = '萌宝上门清冷爹变奶爸';
  const shortTitle = text(shortSource, element('flexVideoList_title__pTP9Y'));
  const queued = fixture([shortTitle], [], async () => ({translations: ['Bé cưng đến nhà, ông bố lạnh lùng hóa bố bỉm']}));
  const timers = new Map();
  Object.assign(queued.context, {IQCOM_METADATA_CACHE:new Map(), IQCOM_METADATA_QUEUE:[],
    setTimeout:(callback, delay) => {const key = {}; timers.set(key, {callback, delay}); return key;},
    clearTimeout:key => timers.delete(key), pumpIqcomMetadata() {}});
  vm.runInContext(source.slice(source.indexOf('  function requestIqcomMetadata('), source.indexOf('  function setMetadataPending(')), queued.context);
  Object.assign(queued.context, {isFixedUI:()=>false, SKIP:{}, fitCompact() {}});
  vm.runInContext(source.slice(source.indexOf('  function walk('), source.indexOf('  var OBSERVED_ROOTS =')), queued.context);
  queued.context.walk(shortTitle.parentElement);
  assert.equal(queued.context.mayMachineTranslate(shortTitle, '', shortSource), false);
  const catalogJob = queued.context.IQCOM_METADATA_QUEUE[0];
  const deadline = [...timers.values()].find(timer => timer.delay === 1500);
  assert.equal(deadline,undefined,'Waiting in the queue must not prematurely enable machine translation');
  queued.context.MACHINE_COPY.set(shortSource,'Bản dịch máy cũ');
  await queued.context.localizeRemaining();
  assert.equal(shortTitle.nodeValue,shortSource,'A cached machine name stays hidden while iq.com is still pending');
  assert.equal(queued.requests.length,0,'Do not start machine translation before the catalog responds');
  catalogJob.resolve({title:'Tên Việt chính thức', sourceTitle:shortSource});
  await Promise.all(queued.pending);
  assert.equal(shortTitle.nodeValue,'Tên Việt chính thức','The first translated name is the official name');
  queued.context.walk(shortTitle.parentElement);
  await Promise.all(queued.pending);
  assert.equal(shortTitle.nodeValue, 'Tên Việt chính thức');
  assert.equal(queued.context.IQCOM_METADATA_QUEUE.length, 1, 'Retry reuses the completed catalog request');

  const storage = new Map();
  function catalogFixture() {
    const result=fixture([]);
    Object.assign(result.context,{IQCOM_METADATA_CACHE:new Map(),IQCOM_METADATA_QUEUE:[],IQCOM_METADATA_ACTIVE:0,
      localStorage:{getItem:key=>storage.get(key),setItem:(key,value)=>storage.set(key,value)}});
    vm.runInContext(source.slice(source.indexOf('  function catalogMetadataCopy('),source.indexOf('  function setMetadataPending(')),result.context);
    return result;
  }
  let catalogCalls=0;
  const firstVisit=catalogFixture(), route='international-title?name='+encodeURIComponent('大梦归离');
  firstVisit.context.window.__iqiyiViLocalFetch=async()=>{
    catalogCalls++;
    return {ok:true,json:async()=>({title:'Đại Mộng Quy Ly',sourceTitle:'大梦归离',globalAlbumId:'12345678'})};
  };
  await firstVisit.context.requestIqcomMetadata(route);
  assert.ok(storage.has('iqiyi-vi-catalog-copy-v1'),'Persist successful official metadata for the next page load');
  const nextVisit=catalogFixture();
  nextVisit.context.window.__iqiyiViLocalFetch=async()=>{throw Error('A warm official name should not need a network request');};
  nextVisit.context.loadIqcomMetadataCache();
  assert.equal((await nextVisit.context.requestIqcomMetadata(route)).title,'Đại Mộng Quy Ly');
  assert.equal(catalogCalls,1);
  assert.equal(nextVisit.context.catalogMetadataCopy(route,{title:'未翻译',sourceTitle:'大梦归离'}),null);
  const saved=JSON.parse(storage.get('iqiyi-vi-catalog-copy-v1'));
  saved[0][1].expires=Date.now()-1;
  storage.set('iqiyi-vi-catalog-copy-v1',JSON.stringify(saved));
  const expired=catalogFixture();
  expired.context.loadIqcomMetadataCache();
  assert.equal(expired.context.IQCOM_METADATA_CACHE.size,0,'Expired names are not reused');


  const sharedName = text('大梦归离', element('tilesItem_title_multi__test'));
  const sharedUI = text('大梦归离', element('ui-label'));
  const cached = fixture([sharedName, sharedUI], [['大梦归离', 'Bản dịch trong cache']]);
  await cached.context.localizeRemaining();
  assert.equal(sharedName.nodeValue, '大梦归离');
  assert.equal(sharedUI.nodeValue, 'Bản dịch trong cache', 'Cache is scoped per node, not banned for an entire string');

  const recycled = text('管理', element('ui-label'));
  const race = fixture([recycled], [], async () => {
    recycled.parentElement.className = 'tilesItem_title_multi__test';
    return {translations: ['Quản lý']};
  });
  await race.context.localizeRemaining();
  assert.equal(recycled.nodeValue, '管理', 'Recheck metadata identity when an in-flight response arrives');

  for (const className of ['filmFeed_title__test','filmFeed_rank_item_title__test','thumbnail_thumbnailItemTitle__test',
    'flexVideoList_title__test','tilesItem_title_multi__test','videoListItem_title__test','videoList_videoTitle__test',
    'webHead_title__test','NavHeader_item__test','rvi__tit1','main-title','site-piclist_info_title']) {
    assert.equal(f.context.isMovieTitleNode(text('测试影片', element(className))), true, className);
  }
  for (const className of ['starList_name__test','StarHeader_name__test','follow_user_name__test',
    'RelatedPeopleSection_name__test','info_starNameText__test','filmFeed_actName__test']) {
    assert.equal(f.context.isActorNameNode(text('演员甲', element(className))), true, className);
  }
  const suggestion = element('search-board-item');
  suggestion.querySelector = () => ({textContent:'Nhân vật'});
  const actorSuggestion = text('白鹿', element('search-board-item_title', suggestion));
  assert.equal(f.context.isActorNameNode(actorSuggestion), true);
  assert.equal(f.context.isMovieTitleNode(actorSuggestion), false, 'Person suggestions take precedence over generic title classes');
  assert.equal(f.context.isActorNameNode(text('白鹿', element('name ', element('charactor-info')))), true);
  assert.equal(f.context.isActorNameNode(text('电视剧 / 2026年 / 白鹿', element('search-board-item_desc'))), true);
  assert.equal(f.context.isMovieTitleNode(text('猜你喜欢', element('videoCards_title__test'))), false);

  const artist = text('任重', element('starList_name__test'));
  const artists = fixture([artist]);
  vm.runInContext(source.slice(source.indexOf('  function localizeActorPrefix('), source.indexOf('  function requestInternationalTitle(')), artists.context);
  artists.context.requestInternationalActor(artist, artist.nodeValue);
  assert.equal(artist.nodeValue, 'Nhiệm Trọng', 'Crew names use the verified catalog name');
  const unlisted = text('演员甲', element('follow_user_name__test'));
  const unknownArtist = fixture([unlisted], [], async () => ({translations:['Tên nghệ sĩ dịch máy']}));
  vm.runInContext(source.slice(source.indexOf('  function localizeActorPrefix('), source.indexOf('  function requestInternationalTitle(')), unknownArtist.context);
  unknownArtist.context.requestIqcomMetadata = async () => ({});
  Object.assign(unknownArtist.context, {isFixedUI:()=>false, SKIP:{}, fitCompact() {}});
  vm.runInContext(source.slice(source.indexOf('  function walk('), source.indexOf('  var OBSERVED_ROOTS =')), unknownArtist.context);
  unknownArtist.context.walk(unlisted.parentElement);
  await Promise.all(unknownArtist.pending);
  await unknownArtist.context.localizeRemaining();
  assert.equal(unlisted.nodeValue, 'Tên nghệ sĩ dịch máy', 'Unknown actors retain machine fallback');

  const tab = documentTitle('爱奇艺 iQIYI-热门独播剧集在线观看');
  const titles = fixture([], [], undefined, tab);
  const originalTitleText = tab.firstChild;
  titles.context.translateDocumentTitle();
  assert.equal(tab.textContent, 'iQIYI – Xem phim và chương trình trực tuyến');
  assert.equal(tab.firstChild, originalTitleText, 'Keep the page-owned title text node');
  tab.firstChild.nodeValue = '爱奇艺-中国领先的在线视频平台-海量正版高清视频在线观看';
  titles.context.translateDocumentTitle();
  assert.equal(tab.textContent, 'iQIYI – Xem phim và video trực tuyến', 'Reapply after an SPA title update');
  tab.firstChild.nodeValue = '卿卿日常第3集-电视剧全集-完整版视频在线观看-爱奇艺';
  titles.context.translateDocumentTitle();
  assert.equal(tab.textContent, 'Khanh Khanh Nhật Thường (Tân Xuyên Nhật Thường) · Tập 3 – iQIYI');
  assert.equal(titles.context.localizePageTitle(tab.textContent), tab.textContent, 'Formatting is idempotent');

  const empty = documentTitle('');
  fixture([], [], undefined, empty).context.translateDocumentTitle();
  assert.equal(empty.textContent, 'iQIYI', 'An empty native page title gets the app name');
  const episode = documentTitle('大梦归离第2集-电视剧全集-完整版视频在线观看-爱奇艺');
  const episodePage = fixture([], [], undefined, episode);
  episodePage.context.location.href = 'https://www.iqiyi.com/v_12345678.html';
  episodePage.context.location.pathname = '/v_12345678.html';
  episodePage.context.translateDocumentTitle();
  await Promise.all(episodePage.pending);
  assert.equal(episode.textContent, 'Đại Mộng Quy Ly · Tập 2 – iQIYI', 'Use the official movie name in the window/tab title');

  const noCatalog = documentTitle('未收录片名-电影-高清完整版视频在线观看-爱奇艺');
  const titleFallback = fixture([], [], async () => ({translations:['Phim thử nghiệm']}), noCatalog);
  titleFallback.context.translateDocumentTitle();
  await titleFallback.context.localizeRemaining();
  assert.equal(noCatalog.textContent, 'Phim thử nghiệm – iQIYI', 'Head titles enter machine fallback despite having no layout box');

  const stale = documentTitle('大梦归离-电视剧全集-爱奇艺');
  const navigation = fixture([], [], undefined, stale);
  navigation.context.location.href = 'https://www.iqiyi.com/v_12345678.html';
  navigation.context.location.pathname = '/v_12345678.html';
  let finishOldTitle;
  navigation.context.requestIqcomMetadata = () => new Promise(resolve => { finishOldTitle = resolve; });
  navigation.context.translateDocumentTitle();
  stale.firstChild.nodeValue = '爱奇艺 iQIYI-热门独播剧集在线观看';
  navigation.context.translateDocumentTitle();
  finishOldTitle({title:'Đại Mộng Quy Ly',sourceTitle:'大梦归离'});
  await Promise.all(navigation.pending);
  assert.equal(stale.textContent, 'iQIYI – Xem phim và chương trình trực tuyến', 'An old response cannot overwrite the next page title');
  const expiredBridge = fixture([text('自定义界面说明',element('ui-label'))],[],async()=>{
    expiredBridge.context.window.__iqiyiViBridgeExpired=true;
    throw Error('Extension context invalidated.');
  });
  const bridgeWarnings=[];
  expiredBridge.context.console={warn:message=>bridgeWarnings.push(message)};
  await expiredBridge.context.localizeRemaining();
  await expiredBridge.context.localizeRemaining();
  assert.equal(expiredBridge.requests.length,1,'A reloaded extension stops old automatic translation requests');
  assert.equal(bridgeWarnings.length,0,'Expected extension invalidation does not fill the extension error list');
  console.log('Title checks passed: official-name priority, persistent catalog cache, actors, recycled nodes, partial batches, isolated retries and expired bridge.');
})().catch(error => { console.error(error); process.exitCode = 1; });
