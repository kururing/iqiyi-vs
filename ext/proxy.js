/* Proxy settings stay in the extension worker; pages never receive credentials. */
importScripts("local-api-worker.js", "iqcom-session.js");
const IQIYI_PROXY_DOMAINS = ["iqiyi.com", "qiyi.com", "qiyipic.com", "iqiyipic.com", "iqiyicloud.com", "qy.net"];
let currentProxy = null;
let syncing = null;
const authAttempts = new Set();

function isIqiyiHost(host) {
  host = host.toLowerCase().replace(/\.$/, "");
  return IQIYI_PROXY_DOMAINS.some(domain => host === domain || host.endsWith("." + domain));
}

function proxyConfig(proxy) {
  const host = proxy.host.includes(":") ? "[" + proxy.host.replace(/^\[|\]$/g, "") + "]" : proxy.host;
  return {mode: "pac_script", pacScript: {mandatory: true, data:
    "function FindProxyForURL(url, host) {host = host.toLowerCase().replace(/\\.$/, '');" +
    "var domains = " + JSON.stringify(IQIYI_PROXY_DOMAINS) + ";" +
    "for (var i=0; i<domains.length; i++) {if (host === domains[i] || " +
    "host.slice(-(domains[i].length+1)) === '.'+domains[i]) return " +
    JSON.stringify("PROXY " + host + ":" + proxy.port) + ";} return 'DIRECT';}"}};
}

// Session storage is private to trusted extension contexts and survives worker restarts.
const proxyReady = chrome.storage.session.get("iqiyiProxy").then(stored => {
  currentProxy = stored.iqiyiProxy || null;
});

function syncProxy() {
  if (syncing) return syncing;
  syncing = (async () => {
    await proxyReady;
    const tokenResponse = await fetch(chrome.runtime.getURL("proxy-token.json"), {cache: "no-store"});
    if (!tokenResponse.ok) throw Error("Mở lại app quản lý phụ đề để kết nối proxy web.");
    const {token} = await tokenResponse.json();
    const response = await fetch("http://127.0.0.1:18766/api/browser-proxy", {
      headers: {"X-Iqiyi-Token": token}, cache: "no-store", credentials: "omit",
      signal: AbortSignal.timeout(5000)
    });
    if (!response.ok) throw Error("Không đồng bộ được proxy web: HTTP " + response.status);
    const {proxy} = await response.json();
    const settings = await chrome.proxy.settings.get({incognito: false});
    if (!proxy) {
      if (settings.levelOfControl === "controlled_by_this_extension") {
        await chrome.proxy.settings.clear({scope: "regular"});
      }
    } else {
      if (!["controllable_by_this_extension", "controlled_by_this_extension"].includes(settings.levelOfControl)) {
        throw Error("Proxy trình duyệt đang do chính sách hoặc tiện ích khác quản lý.");
      }
      const config = proxyConfig(proxy);
      if (settings.value.mode !== config.mode || settings.value.pacScript?.data !== config.pacScript.data ||
          settings.value.pacScript?.mandatory !== true) {
        await chrome.proxy.settings.set({value: config, scope: "regular"});
      }
    }
    await chrome.storage.session.set({iqiyiProxy: proxy});
    currentProxy = proxy;
  })().finally(() => { syncing = null; });
  return syncing;
}

chrome.webRequest.onAuthRequired.addListener((details, callback) => {
  if (!details.isProxy || !isIqiyiHost(new URL(details.url).hostname)) {
    callback({});
    return;
  }
  syncProxy().catch(() => {}).then(() => {
    const proxy = currentProxy;
    if (!proxy || !proxy.username || details.challenger.host.replace(/^\[|\]$/g, "").toLowerCase() !== proxy.host.toLowerCase() ||
        details.challenger.port !== proxy.port) {
      callback({});
    } else if (authAttempts.has(details.requestId)) {
      callback({cancel: true});
    } else {
      authAttempts.add(details.requestId);
      callback({authCredentials: {username: proxy.username, password: proxy.password}});
    }
  });
}, {urls: ["<all_urls>"]}, ["asyncBlocking"]);

function clearAuthAttempt(details) { authAttempts.delete(details.requestId); }
chrome.webRequest.onCompleted.addListener(clearAuthAttempt, {urls: ["<all_urls>"]});
chrome.webRequest.onErrorOccurred.addListener(clearAuthAttempt, {urls: ["<all_urls>"]});
chrome.alarms.onAlarm.addListener(alarm => {
  if (alarm.name === "iqiyi-proxy") syncProxy().catch(error => console.warn(error.message));
});
chrome.alarms.create("iqiyi-proxy", {periodInMinutes: 0.5});
syncProxy().catch(error => console.warn(error.message));
