/* Resolve and stream Vietnamese AAC in the extension; no localhost dependency. */
const audioJobs = new Map(), audioSources = new Map(), audioControllers = new Map();
let audioGeneration = 0;
const audioReady = chrome.storage.session.get("iqcomAudioSources").then(stored => {
  for (const row of stored.iqcomAudioSources || []) if (row.stream || row.expires > Date.now()) audioSources.set(row.tvid, row);
});
function audioMediaUrl(value) {
  const url = new URL(value);
  if (!["http:", "https:"].includes(url.protocol) || url.username || url.password || url.hash ||
      !["iqiyi.com", "iq.com", "71edge.com"].some(host => url.hostname.endsWith("." + host)) ||
      (url.port && !["80", "443"].includes(url.port) && !(url.protocol === "https:" && url.hostname.endsWith(".71edge.com") && url.port === "8402"))) {
    throw Error("Địa chỉ âm thanh iq.com không hợp lệ.");
  }
  url.protocol = "https:";
  return url.href;
}
async function audioFetch(url, signal, headers = {}) {
  const response = await fetch(audioMediaUrl(url), {credentials:"omit",redirect:"error",
    signal:AbortSignal.any([...(signal ? [signal] : []), AbortSignal.timeout(20000)]),headers});
  if (!response.ok) throw Error("Không tải được âm thanh iq.com (HTTP " + response.status + ").");
  return response;
}
async function audioBytes(response, limit) {
  const bytes = new Uint8Array(await response.arrayBuffer());
  if (bytes.length > limit) throw Error("Dữ liệu âm thanh iq.com quá lớn.");
  return bytes;
}
function audioPageUrl(suffix) {
  const url = new URL(suffix, "https://www.iq.com/play/");
  if (url.origin !== "https://www.iq.com" || !url.pathname.startsWith("/play/") || url.username || url.password) throw Error("Liên kết tập iq.com không hợp lệ.");
  url.searchParams.set("lang", "vi_vn");
  return url.href;
}
async function audioPage(suffix, signal) {
  const response = await fetch(audioPageUrl(suffix), {credentials:"include",signal});
  audioPageUrl(response.url);
  if (!response.ok) throw Error("Không đọc được trang tập phim iq.com.");
  const text = new TextDecoder().decode(await audioBytes(response, 4000000));
  const match = text.match(/<script\b[^>]*id=["']__NEXT_DATA__["'][^>]*>([\s\S]*?)<\/script>/);
  if (!match) throw Error("iq.com chưa trả metadata tập phim.");
  return JSON.parse(match[1]);
}
function audioTrack(data, tvid, album) {
  if (String(data?.tvid) !== tvid || String(data?.aid) !== album || data?.ctl?.boss_not_pass) return null;
  const tracks = (data.program?.audio || []).filter(row => String(row.lid) === "161" && row.cf === "aac" && row.ff === "amp4" && row.fs?.length);
  return tracks.find(row => row._selected) || tracks[0];
}
// Let iq.com's own player sign requests with this browser's existing login.
// Only a tab created here can supply a DASH URL; credentials never reach iQIYI pages.
async function audioBrowserDash(pageUrl, tvid, album, signal) {
  let tab, finish, closed = false, probeTimer;
  const result = new Promise((resolve, reject) => { finish = (data, error) => error ? reject(error) : resolve(data); });
  result.catch(() => {});
  const seen = new Set();
  function capture(details) {
    if (closed || details.tabId !== tab?.id || seen.size >= 3) return;
    const url = new URL(details.url);
    if (url.protocol !== "https:" || !["cache.video.iqiyi.com", "cache.video.iq.com"].includes(url.hostname) || url.pathname !== "/dash" || url.searchParams.get("tvid") !== tvid || seen.has(url.href)) return;
    seen.add(url.href);
    audioFetch(url.href, signal).then(response => audioBytes(response, 4000000)).then(bytes => {
      const raw = new TextDecoder().decode(bytes).trim();
      const payload = JSON.parse(raw.startsWith("{") ? raw : raw.slice(raw.indexOf("(") + 1, raw.lastIndexOf(")")));
      if (audioTrack(payload.data, tvid, album)) finish(payload.data);
    }).catch(() => {});
  }
  const abort = () => finish(null, signal.reason);
  async function probe() {
    if (closed || !tab) return;
    try {
      const results = await chrome.scripting.executeScript({target:{tabId:tab.id},world:"MAIN",func:() => {
        if (location.origin !== "https://www.iq.com" || !location.pathname.startsWith("/play/")) return null;
        // A background tab otherwise waits for visibility before requesting playback metadata.
        if (!window.__iqiyiViAudioProbe) {
          window.__iqiyiViAudioProbe = true;
          Object.defineProperty(document, "hidden", {configurable:true,get:() => false});
          Object.defineProperty(document, "visibilityState", {configurable:true,get:() => "visible"});
          document.dispatchEvent(new Event("visibilitychange"));
          const timer = setInterval(() => {
            const video = document.querySelector("video");
            if (video) { video.muted = true; video.play().catch(() => {}); }
          }, 1000);
          setTimeout(() => clearInterval(timer), 20000);
        }
        try { return JSON.parse(document.getElementById("__NEXT_DATA__")?.textContent || "{}").props?.initialProps?.pageProps?.prePlayerData?.dash?.data || null; }
        catch { return null; }
      }});
      const data = results[0]?.result;
      if (audioTrack(data, tvid, album)) finish(data);
    } catch {}
    if (!closed) probeTimer = setTimeout(probe, 1000);
  }
  chrome.webRequest.onBeforeRequest.addListener(capture, {urls:["https://cache.video.iqiyi.com/dash*","https://cache.video.iq.com/dash*"]});
  signal.addEventListener("abort", abort, {once:true});
  const timer = setTimeout(() => finish(null, Error("iq.com chưa cấp tiếng Việt. Kiểm tra đăng nhập iq.com, quyền xem tập và khu vực rồi thử lại.")), 25000);
  try {
    if (signal.aborted) throw signal.reason;
    // Mute before navigation so the helper tab cannot play a second soundtrack.
    tab = await chrome.tabs.create({url:"about:blank",active:false});
    await chrome.tabs.update(tab.id, {muted:true});
    await chrome.tabs.update(tab.id, {url:pageUrl});
    probeTimer = setTimeout(probe, 500);
    return await result;
  } finally {
    closed = true; clearTimeout(timer); clearTimeout(probeTimer);
    signal.removeEventListener("abort", abort);
    chrome.webRequest.onBeforeRequest.removeListener(capture);
    if (tab) await chrome.tabs.remove(tab.id).catch(() => {});
  }
}
async function resolveBrowserAudio(tvid, signal) {
  const domestic = (await publicJson("https://pcw-api.iqiyi.com/video/video/baseinfo/" + tvid, signal)).data || {};
  const order = Number(domestic.order);
  if (String(domestic.tvId) !== tvid || !Number.isInteger(order) || order < 1) throw Error("Chưa xác nhận được phim và số tập đang phát.");
  const mapping = await publicMovieTitle(String(domestic.albumId), signal);
  if (!mapping.globalAlbumId) throw Error("Chưa tìm được phim khớp chính xác trên iq.com.");
  const original = await catalogAlbum(mapping.globalAlbumId, "zh_cn", signal);
  const name = cleanPublicText(original.albumName || original.name);
  const vietnamese = row => (row.audioInfoList || []).some(audio => String(audio.id) === "161");
  let selected = vietnamese(original) ? original : null;
  if (!selected) {
    const rows = (await searchCatalog(name, "zh_cn", signal)).data?.epg || [], candidates = new Map();
    const base = title => cleanPublicText(title).replace(/[（(]?\s*越南(?:语|語)(?:配音)?版\s*[）)]?$/, "").trim();
    for (const row of rows) {
      const id = String(row.qipuId || ""), title = cleanPublicText(row.name);
      if (![0, 1].includes(row.type) || !/^\d{8,24}$/.test(id) || title === base(title) || base(title) !== name) continue;
      const candidate = await catalogAlbum(id, "zh_cn", signal);
      if (base(candidate.albumName || candidate.name) === name && vietnamese(candidate) &&
          String(candidate.publishTime || "").slice(0, 4) === String(original.publishTime || "").slice(0, 4) &&
          candidate.chnId === original.chnId && candidate.total === original.total) candidates.set(id, candidate);
    }
    if (candidates.size !== 1) throw Error("Chưa tìm được duy nhất một bản tiếng Việt khớp phim trên iq.com.");
    selected = candidates.values().next().value;
  }
  const album = String(selected.qipuId), localized = await catalogAlbum(album, "vi_vn", signal);
  let page = await audioPage(localized.playLocSuffix, signal);
  const lists = page.props?.initialState?.play?.cachePlayList || {}, episodes = new Map();
  for (const row of Object.values(lists).flat()) {
    const id = String(row.tvId || row.qipuId || "");
    if (String(row.albumId) === album && Number(row.order) === order && String(row.contentType) === "1" && /^\d{8,24}$/.test(id)) episodes.set(id, row);
  }
  if (episodes.size !== 1) throw Error("Chưa tìm được đúng tập của bản âm thanh Việt.");
  const [globalTvid, episode] = episodes.entries().next().value;
  if (String(localized.defaultTvId) !== globalTvid) page = await audioPage(episode.playLocSuffix, signal);
  let data = page.props?.initialProps?.pageProps?.prePlayerData?.dash?.data;
  let track = audioTrack(data, globalTvid, album);
  if (!track) {
    data = await audioBrowserDash(audioPageUrl(episode.playLocSuffix), globalTvid, album, signal);
    track = audioTrack(data, globalTvid, album);
  }
  const duration = Number(track?.duration), domesticDuration = Number(domestic.durationSec);
  if (!(duration > 0 && duration <= 86400 && domesticDuration > 0 && domesticDuration <= 86400)) throw Error("Chưa có thời lượng để đồng bộ âm thanh Việt.");
  if (!Array.isArray(track.fs) || track.fs.length < 2 || track.fs.length > 512) throw Error("Danh sách âm thanh iq.com không hợp lệ.");
  let size = 0;
  for (const part of track.fs) {
    if (typeof part.l !== "string" || part.l.length > 8192 || /[\x00-\x20]/.test(part.l) ||
        !/^\/v0\/[\w/.-]+\.amp4(?:\?[^#]*)?$/.test(part.l) || !Number.isInteger(part.b) || part.b <= 0 || part.b > 64000000) throw Error("Đoạn âm thanh iq.com không hợp lệ.");
    size += part.b;
  }
  if (size > 1000000000) throw Error("Track âm thanh quá lớn.");
  return {tvid,stream:crypto.randomUUID(),dd:audioMediaUrl(data.dd).replace(/\/$/, ""),parts:track.fs,
    duration,shiftSeconds:domesticDuration-duration,episode:order,expires:Date.now()+15*60000};
}
async function audioLocation(source, index, signal) {
  const response = await audioFetch(source.dd + source.parts[index].l, signal);
  const payload = JSON.parse(new TextDecoder().decode(await audioBytes(response, 32000)));
  return audioMediaUrl(payload.l);
}
async function audioInit(source, signal) {
  if (source.init) return source.init;
  let bytes = await audioBytes(await audioFetch(await audioLocation(source, 0, signal), signal), 4000000);
  if (bytes[0] === 31 && bytes[1] === 139) bytes = await audioBytes(new Response(new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"))), 4000000);
  const markers = new TextDecoder("latin1").decode(bytes);
  if (markers.slice(4, 8) !== "ftyp" || !markers.includes("moov") || !markers.includes("mp4a") || /enca|sinf|tenc/.test(markers)) throw Error("Định dạng âm thanh này chưa được hỗ trợ.");
  source.init = bytes;
  return bytes;
}
async function saveAudioSources() {
  await chrome.storage.session.set({iqcomAudioSources:[...audioSources.values()].map(({init, ...row}) => row)});
}
function clearAudioSources() {
  audioGeneration++;
  audioControllers.forEach(controller => controller.abort());
  audioControllers.clear(); audioJobs.clear(); audioSources.clear();
  return saveAudioSources();
}
async function browserAudioRequest(url, message) {
  await audioReady;
  if (url.pathname === "/api/audio-settings") {
    const settings = JSON.parse(message.body || "{}");
    if (typeof settings.enabled !== "boolean") throw Error("Cài đặt âm thanh không hợp lệ.");
    await clearAudioSources();
    await chrome.storage.local.set({iqcomAudioEnabled:settings.enabled});
    return audioJson({enabled:settings.enabled});
  }
  const enabled = !!(await chrome.storage.local.get("iqcomAudioEnabled")).iqcomAudioEnabled;
  const tvid = url.searchParams.get("tvid") || "";
  if (tvid && !/^\d{8,24}$/.test(tvid)) throw Error("Mã tập iQIYI không hợp lệ.");
  let source = audioSources.get(tvid);
  if (source && !source.stream && source.expires <= Date.now()) { audioSources.delete(tvid); source = null; }
  if (enabled && source?.stream && source.expires <= Date.now() && !audioJobs.has(tvid)) {
    source.expires = Date.now() + 180000;
    const generation = audioGeneration;
    const controller = new AbortController(), signal = AbortSignal.any([controller.signal, AbortSignal.timeout(60000)]);
    audioControllers.set(tvid, controller);
    const job = resolveBrowserAudio(tvid, signal).then(async row => {
      const init = await audioInit(row, signal);
      const original = await audioInit(source, signal);
      if (generation === audioGeneration && audioSources.get(tvid) === source &&
          source.parts.length === row.parts.length && source.parts.every((part, index) => part.b === row.parts[index].b) &&
          original.length === init.length && original.every((byte, index) => byte === init[index])) {
        source.dd = row.dd; source.parts = row.parts; source.expires = Date.now() + 15*60000;
        await saveAudioSources();
      } else source.expires = Date.now() + 30000;
    }).catch(() => { source.expires = Date.now() + 30000; }).finally(() => {
      if (audioJobs.get(tvid) === job) audioJobs.delete(tvid);
      if (audioControllers.get(tvid) === controller) audioControllers.delete(tvid);
    });
    audioJobs.set(tvid, job);
  }
  if (enabled && tvid && !source && !audioJobs.has(tvid) && audioJobs.size < 2) {
    const generation = audioGeneration;
    const controller = new AbortController(), signal = AbortSignal.any([controller.signal, AbortSignal.timeout(60000)]);
    audioControllers.set(tvid, controller);
    const job = resolveBrowserAudio(tvid, signal).then(async row => {
      await audioInit(row, signal);
      if (generation !== audioGeneration) return;
      audioSources.delete(tvid);
      while (audioSources.size >= 4) audioSources.delete(audioSources.keys().next().value);
      audioSources.set(tvid, row); await saveAudioSources();
    }).catch(error => {
      if (generation === audioGeneration) {
        while (audioSources.size >= 4) audioSources.delete(audioSources.keys().next().value);
        audioSources.set(tvid, {tvid,error:error.message,expires:Date.now()+30000});
      }
    }).finally(() => {
      if (audioJobs.get(tvid) === job) audioJobs.delete(tvid);
      if (audioControllers.get(tvid) === controller) audioControllers.delete(tvid);
    });
    audioJobs.set(tvid, job);
  }
  return audioJson({enabled,loading:enabled && !!tvid && !source,available:enabled && !!source?.stream,
    stream:source?.stream || "",duration:source?.duration,shiftSeconds:source?.shiftSeconds,episode:source?.episode,error:source?.error || ""});
}
function audioJson(value) { return {status:200,headers:{"Content-Type":"application/json"},body:JSON.stringify(value)}; }
function audioRange(value, size) {
  if (!value) return [0, size-1];
  const match = /^bytes=(\d*)-(\d*)$/.exec(value);
  if (!match || !(match[1] || match[2])) throw Error("Invalid range");
  const start = match[1] ? Number(match[1]) : Math.max(0, size-Number(match[2]));
  const end = match[1] && match[2] ? Math.min(size-1, Number(match[2])) : size-1;
  if (!Number.isSafeInteger(start) || !Number.isSafeInteger(end) || start < 0 || start > end || start >= size) throw Error("Invalid range");
  return [start, end];
}
async function browserAudioStream(request) {
  await audioReady;
  const url = new URL(request.url), source = audioSources.get(url.searchParams.get("tvid"));
  if (!source?.stream || source.stream !== url.searchParams.get("stream") ||
      !(await chrome.storage.local.get("iqcomAudioEnabled")).iqcomAudioEnabled) return new Response("Audio expired", {status:403});
  if (!["GET", "HEAD"].includes(request.method)) return new Response(null, {status:405});
  const abort = new AbortController();
  request.signal.addEventListener("abort", () => abort.abort(), {once:true});
  if (request.signal.aborted) abort.abort();
  const signal = abort.signal;
  const init = await audioInit(source, signal), size = init.length + source.parts.slice(1).reduce((n,p) => n+p.b, 0);
  let start, end;
  try { [start, end] = audioRange(request.headers.get("Range"), size); }
  catch { return new Response(null, {status:416,headers:{"Content-Range":"bytes */"+size}}); }
  const headers = {"Content-Type":"audio/mp4","Accept-Ranges":"bytes","Content-Length":String(end-start+1),"Cache-Control":"no-store"};
  if (request.headers.has("Range")) headers["Content-Range"] = `bytes ${start}-${end}/${size}`;
  const status = request.headers.has("Range") ? 206 : 200;
  async function* chunks() {
    if (start < init.length) yield init.slice(start, Math.min(end+1, init.length));
    let offset = init.length;
    for (let i=1; i<source.parts.length && offset <= end; i++) {
      const part = source.parts[i], next = offset + part.b;
      if (next > start) {
        const low = Math.max(0, start-offset), high = Math.min(part.b-1, end-offset);
        const response = await audioFetch(await audioLocation(source, i, signal), signal, {Range:`bytes=${low}-${high}`});
        // Never trust a CDN which ignores a nonzero range or changes segment length.
        if (response.status !== 206 || response.headers.get("Content-Range") !== `bytes ${low}-${high}/${part.b}`) throw Error("CDN âm thanh trả sai vùng dữ liệu.");
        const reader = response.body.getReader(); let remaining = high-low+1;
        try {
          while (remaining) {
            const {done,value} = await reader.read();
            if (done || value.length > remaining) throw Error("Dữ liệu âm thanh bị thiếu hoặc sai độ dài.");
            remaining -= value.length; yield value;
          }
        } finally { await reader.cancel().catch(() => {}); }
      }
      offset = next;
    }
  }
  const iterator = chunks();
  const body = request.method === "HEAD" ? null : new ReadableStream({
    async pull(controller) { try { const step = await iterator.next(); if (step.done) controller.close(); else controller.enqueue(step.value); } catch (error) { abort.abort(); controller.error(error); } },
    async cancel() { abort.abort(); await iterator.return(); }
  });
  return new Response(body, {status,headers});
}
self.addEventListener("fetch", event => {
  const url = new URL(event.request.url);
  if (url.protocol === "chrome-extension:" && url.host === chrome.runtime.id && url.pathname === "/audio-stream.mp4") {
    event.respondWith(browserAudioStream(event.request).catch(() => new Response("Audio unavailable", {status:502})));
  }
});
chrome.cookies.onChanged.addListener(({cookie}) => {
  if (["iq.com", "www.iq.com"].includes(cookie.domain.replace(/^\./, "")) && /^(I00001|I00019|P00001|P00002|P00003)$/.test(cookie.name)) {
    audioReady.then(clearAudioSources).catch(() => {});
  }
});
chrome.declarativeNetRequest.updateSessionRules({removeRuleIds:[16101],addRules:[{
  id:16101,priority:2,action:{type:"modifyHeaders",requestHeaders:[{header:"Referer",operation:"set",value:"https://www.iq.com/"}]},
  condition:{initiatorDomains:[chrome.runtime.id],requestDomains:["iqiyi.com","iq.com","71edge.com"],resourceTypes:["xmlhttprequest"]}
}]}).catch(() => {});
