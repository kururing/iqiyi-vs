/* Public localization runs in the extension, independently of the subtitle manager. */
const publicLocalizationCache = new Map();
const publicTitleAliases = new Map();
const publicActorNames = new Map();
// The Vietnam catalog applies to both Chinese identity checks and Vietnamese labels.
const IQCOM_CATALOG_REGION = "vn";
const hasChinese = value => /[\u3400-\u9fff\uf900-\ufaff]/.test(value);
const cleanPublicText = value => String(value || "").replace(/<[^>]*>/g, "").replace(/\s+/g, " ").trim();
const publicTitleKey = value => cleanPublicText(value).replace(/[\s《》「」『』【】]/g, "").toLowerCase();
const publicSearchKey = value => String(value).normalize("NFD").toLowerCase().replace(/đ/g, "d").replace(/[^a-z0-9]/g, "");

async function publicJson(url, signal, options = {}) {
  const response = await fetch(url, {...options, signal, credentials: "omit", redirect: "error"});
  if (!response.ok) throw Error("API Việt hóa trả HTTP " + response.status);
  const body = await response.arrayBuffer();
  if (body.byteLength > 4000000) throw Error("Dữ liệu Việt hóa quá lớn.");
  try {
    return JSON.parse(new TextDecoder("utf-8", {fatal: true}).decode(body));
  } catch {
    throw Error("Dữ liệu Việt hóa nhận về bị thiếu hoặc không hợp lệ; hãy thử lại.");
  }
}

function catalogParams(langCode, extra = {}) {
  return new URLSearchParams({platformId: "3", modeCode: IQCOM_CATALOG_REGION, langCode, deviceId: "ew", ...extra});
}

function searchCatalog(key, langCode, signal, dataType = "1;should,2;should") {
  return publicJson("https://pcw-api.iq.com/api/search2?" + catalogParams(langCode, {
    key, pn: "1", ps: "20", intentPn: "1", intentPs: "0", chnId: "0", dataType, isVip: "0"
  }), signal);
}

async function catalogAlbum(id, langCode, signal) {
  const payload = await publicJson("https://pcw-api.iq.com/api/epgInfo/" + id + "?" +
    catalogParams(langCode, {platformId: "4"}), signal);
  return [0, "0"].includes(payload.code) && String(payload.data?.qipuId) === id ? payload.data : {};
}

function rememberPublicActor(sourceName, name, id) {
  if (!sourceName || !hasChinese(sourceName) || !name || name.length > 200 ||
      /[\u3400-\u9fff\uf900-\ufaff\x00-\x1f<>]/.test(name) || !/^\d{1,24}$/.test(id)) return;
  if (publicActorNames.size >= 512) publicActorNames.delete(publicActorNames.keys().next().value);
  publicActorNames.set(sourceName, {sourceName, name, id});
}

async function publicMovieTitle(identifier, signal) {
  if (!/^[A-Za-z0-9]{8,24}$/.test(identifier)) throw Error("Mã phim iQIYI không hợp lệ.");
  if (!/^\d+$/.test(identifier)) {
    let value = 0n;
    for (const digit of identifier.toLowerCase()) value = value * 36n + BigInt(parseInt(digit, 36));
    value ^= 0x75706971676cn;
    identifier = String(value < 900000n ? 100n * (value + 900000n) : value);
  }
  let domestic = {};
  for (const kind of identifier.endsWith("01") ? ["album", "video"] : ["video", "album"]) {
    const payload = await publicJson(`https://pcw-api.iqiyi.com/${kind}/${kind}/baseinfo/${identifier}`, signal);
    if (payload.code === "A00000" && payload.data && typeof payload.data === "object") {
      domestic = payload.data;
      break;
    }
  }
  const sourceTitle = cleanPublicText(domestic.albumName || domestic.name);
  const result = {title: "", sourceTitle};
  if (!hasChinese(sourceTitle)) return result;
  const date = String(domestic.year || domestic.publishDate || domestic.firstVideo?.publishDate || "");
  const year = /^(19|20)\d{2}/.test(date) ? date.slice(0, 4) : "";
  const matches = row => publicTitleKey(row.albumName || row.name) === publicTitleKey(sourceTitle) &&
    (!year || String(row.publishTime || "").slice(0, 4) === year) &&
    (!domestic.channelId || String(row.chnId) === String(domestic.channelId));
  const candidates = new Map();
  // Some regional editions are missing from iq.com's search index.
  const regionalId = {"236709101": "249155501"}[String(domestic.albumId || identifier)];
  if (regionalId) {
    const row = await catalogAlbum(regionalId, "zh_cn", signal);
    if (matches(row)) candidates.set(regionalId, row);
  }
  if (!candidates.size) {
    const payload = await searchCatalog(sourceTitle, "zh_cn", signal);
    if ([0, "0"].includes(payload.code)) {
      for (const row of payload.data?.epg || []) {
        const id = String(row.qipuId || row.albumId || "");
        if ([0, 1].includes(row.type) && /^\d{8,24}$/.test(id) && matches(row)) candidates.set(id, row);
      }
    }
  }
  if (!candidates.size) {
    const id = String(domestic.albumId || identifier);
    const row = await catalogAlbum(id, "zh_cn", signal);
    if (matches(row)) candidates.set(id, row);
  }
  // Preserve the original title when several editions could match.
  if (candidates.size !== 1) return result;
  const [id, source] = candidates.entries().next().value;
  const localized = await catalogAlbum(id, "vi_vn", signal);
  const title = cleanPublicText(localized.albumName || localized.name);
  if (!title || title.length > 200 || hasChinese(title) || (localized.matchedLang ?? 15) !== 15) return result;
  result.title = title;
  result.globalAlbumId = id;
  if (publicTitleAliases.size >= 512) publicTitleAliases.delete(publicTitleAliases.keys().next().value);
  publicTitleAliases.set(sourceTitle, {title, query: sourceTitle});
  const people = data => new Map(["mainActor", "actor", "star", "host", "guest"].flatMap(group =>
    (data.cast?.[group] || []).map(row => [String(row.id), row.n])));
  const localizedPeople = people(localized);
  for (const [personId, name] of people(source)) rememberPublicActor(name, localizedPeople.get(personId), personId);
  return result;
}

async function publicMovieTitleByName(name, signal) {
  name = cleanPublicText(name);
  if (!name || name.length > 200 || !hasChinese(name) || /[\x00-\x1f<>]/.test(name)) {
    throw Error("Tên phim iQIYI không hợp lệ.");
  }
  const result = {title: "", sourceTitle: name};
  const payload = await searchCatalog(name, "zh_cn", signal);
  const rows = [0, "0"].includes(payload.code) && Array.isArray(payload.data?.epg) ? payload.data.epg : [];
  const candidates = new Map();
  for (const row of rows) {
    const id = String(row.qipuId || row.albumId || "");
    if ([0, 1].includes(row.type) && /^\d{8,24}$/.test(id) &&
        publicTitleKey(row.albumName || row.name) === publicTitleKey(name)) candidates.set(id, row);
  }
  if (candidates.size !== 1) return result;
  const [id, row] = candidates.entries().next().value;
  // Search snippets alone are insufficient: verify the full album before using it.
  const original = await catalogAlbum(id, "zh_cn", signal);
  if (publicTitleKey(original.albumName || original.name) !== publicTitleKey(name) ||
      (row.chnId && String(original.chnId) !== String(row.chnId)) ||
      (row.publishTime && String(original.publishTime || "").slice(0, 4) !== String(row.publishTime).slice(0, 4))) return result;
  const localized = await catalogAlbum(id, "vi_vn", signal);
  const title = cleanPublicText(localized.albumName || localized.name);
  if (!title || title.length > 200 || hasChinese(title) || (localized.matchedLang ?? 15) !== 15) return result;
  if (publicTitleAliases.size >= 512) publicTitleAliases.delete(publicTitleAliases.keys().next().value);
  publicTitleAliases.set(name, {title, query: name});
  return {title, sourceTitle: name, globalAlbumId: id};
}

async function publicActorName(name, signal) {
  if (!name || name.length > 80 || !hasChinese(name) || !/^[\p{L}\p{N}_\s·・.（）()\-]+$/u.test(name)) {
    throw Error("Tên diễn viên iQIYI không hợp lệ.");
  }
  if (publicActorNames.has(name)) return publicActorNames.get(name);
  const result = {name: "", sourceName: name, id: ""};
  const payload = await searchCatalog(name, "vi_vn", signal, "4;should");
  const localized = [0, "0"].includes(payload.code) ? payload.data?.starsInfo || {} : {};
  const id = String(localized.qipuId || ""), translated = cleanPublicText(localized.name);
  if (!/^\d{1,24}$/.test(id) || !translated || translated.length > 200 || hasChinese(translated)) return result;
  if (localized.nationalityName !== name) {
    const original = await searchCatalog(name, "zh_cn", signal, "4;should");
    if (![0, "0"].includes(original.code) || original.data?.starsInfo?.name !== name ||
        String(original.data?.starsInfo?.qipuId) !== id) return result;
  }
  rememberPublicActor(name, translated, id);
  return publicActorNames.get(name) || result;
}

async function publicSearch(keyword, signal) {
  if (!keyword || keyword.length > 100 || /[\x00-\x1f\x7f]/.test(keyword)) throw Error("Từ khóa không hợp lệ.");
  const result = {query: keyword, title: keyword, suggestions: []};
  if (hasChinese(keyword)) return result;
  const key = publicSearchKey(keyword);
  function score(title) {
    const candidate = publicSearchKey(title);
    if (candidate === key) return 2;
    if (key.length < 3) return 0;
    if (candidate.includes(key)) return 1 + key.length / candidate.length;
    // Short title strings: edit distance keeps typo suggestions without a dependency.
    let previous = Array.from({length: candidate.length + 1}, (_, index) => index);
    for (let i = 1; i <= key.length; i++) {
      const current = [i];
      for (let j = 1; j <= candidate.length; j++) current[j] = Math.min(
        current[j - 1] + 1, previous[j] + 1, previous[j - 1] + (key[i - 1] === candidate[j - 1] ? 0 : 1));
      previous = current;
    }
    const similarity = 1 - previous[candidate.length] / Math.max(key.length, candidate.length);
    return similarity >= 0.72 ? similarity : 0;
  }
  const candidates = new Map([...publicTitleAliases].filter(([, row]) => score(row.title)));
  const exact = () => [...candidates.values()].filter(row => score(row.title) === 2);
  if (exact().length === 1) return {...result, query: exact()[0].query, title: exact()[0].title};
  const payload = await searchCatalog(keyword, "vi_vn", signal);
  const rows = [0, "0"].includes(payload.code) && Array.isArray(payload.data?.epg) ? payload.data.epg : [];
  const matches = rows.filter(row => [0, 1].includes(row.type) && typeof row.name === "string" && row.name.length <= 200 &&
    !hasChinese(row.name) && score(row.name)).sort((a, b) => score(b.name) - score(a.name));
  for (const row of matches.slice(0, 5)) {
    const id = String(row.qipuId || row.albumId || "");
    if (!/^\d{8,24}$/.test(id)) continue;
    const original = await catalogAlbum(id, "zh_cn", signal);
    const query = cleanPublicText(original.albumName || original.name);
    if (query.length <= 200 && hasChinese(query)) candidates.set(query, {
      title: cleanPublicText(row.name), query, year: String(row.publishTime || "").slice(0, 4)
    });
  }
  if (exact().length === 1) { result.query = exact()[0].query; result.title = exact()[0].title; }
  else result.suggestions = [...candidates.values()].sort((a, b) => score(b.title) - score(a.title)).slice(0, 5);
  return result;
}

async function publicLocalizationRequest(url, message, signal) {
  const key = url.pathname + url.search + (message.body || "");
  const cached = publicLocalizationCache.get(key);
  if (cached && cached.expires > Date.now()) return cached.result;
  let payload;
  if (url.pathname === "/api/localize-remaining") {
    const texts = JSON.parse(message.body || "{}").texts;
    if (!Array.isArray(texts) || !texts.length || texts.length > 8 || texts.some(text =>
        typeof text !== "string" || !text.trim() || text.length > 2000)) throw Error("Nội dung Việt hóa không hợp lệ.");
    const body = new URLSearchParams();
    texts.forEach(text => body.append("q", text));
    const translations = await publicJson("https://clients5.google.com/translate_a/t?client=dict-chrome-ex&sl=zh-CN&tl=vi", signal,
      {method: "POST", headers: {"Content-Type": "application/x-www-form-urlencoded"}, body: body.toString()});
    if (!Array.isArray(translations) || translations.length !== texts.length || translations.some(text =>
        typeof text !== "string" || !text.trim() || text.length > 8000 || hasChinese(text))) {
      throw Error("Dịch nhanh chưa trả đủ nội dung tiếng Việt; sẽ thử lại.");
    }
    payload = {translations};
  } else if (url.pathname === "/api/international-title") {
    payload = url.searchParams.has("id") ? await publicMovieTitle(url.searchParams.get("id") || "", signal) :
      await publicMovieTitleByName(url.searchParams.get("name") || "", signal);
  } else if (url.pathname === "/api/international-actor") {
    payload = await publicActorName((url.searchParams.get("name") || "").trim(), signal);
  } else {
    payload = await publicSearch((url.searchParams.get("q") || "").trim(), signal);
  }
  const result = {status: 200, headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload)};
  if (publicLocalizationCache.size >= 512) publicLocalizationCache.delete(publicLocalizationCache.keys().next().value);
  const found = payload.title || payload.name || payload.translations;
  publicLocalizationCache.set(key, {result, expires: Date.now() + (found ? 3600000 : 120000)});
  return result;
}
