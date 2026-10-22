/* Cookies stay between the extension and localhost; web pages only receive safe status. */
let iqcomSyncing = null;
let iqcomSyncTimer = null;
function scheduleIqcomSync() {
  clearTimeout(iqcomSyncTimer);
  iqcomSyncTimer = setTimeout(() => {
    iqcomSyncTimer = null;
    // If cookies change during a sync, read the latest batch after it completes.
    (iqcomSyncing || Promise.resolve()).catch(() => {}).then(() => syncIqcomSession()).catch(() => {});
  }, 300);
}
function syncIqcomSession(select = false) {
  if (iqcomSyncing) return select ? iqcomSyncing.catch(() => {}).then(() => syncIqcomSession(true)) : iqcomSyncing;
  iqcomSyncing = (async () => {
    const configResponse = await fetch(chrome.runtime.getURL("proxy-token.json"), {cache: "no-store"});
    if (!configResponse.ok) throw Error("Mở lại app quản lý phụ đề để kết nối phiên iq.com.");
    const config = await configResponse.json();
    if (!config.sessionToken) throw Error("Mở lại app quản lý phụ đề để cập nhật kết nối iq.com.");
    const stored = await chrome.storage.local.get("iqcomSourceId");
    let sourceId = stored.iqcomSourceId;
    if (typeof sourceId !== "string" || !/^[A-Za-z0-9_-]{16,128}$/.test(sourceId)) {
      sourceId = crypto.randomUUID();
      await chrome.storage.local.set({iqcomSourceId: sourceId});
    }
    const cookies = await chrome.cookies.getAll({url: "https://www.iq.com/"});
    const response = await fetch("http://127.0.0.1:18766/api/browser-session", {
      method: "POST", headers: {"Content-Type": "application/json", "X-Iqiyi-Token": config.sessionToken},
      body: JSON.stringify({cookies, sourceId, select}), credentials: "omit", signal: AbortSignal.timeout(5000)
    });
    const result = await response.json();
    if (!response.ok) throw Error(result.error || "Không đồng bộ được phiên iq.com.");
    return {state: result};
  })().finally(() => { iqcomSyncing = null; });
  return iqcomSyncing;
}
chrome.runtime.onMessage.addListener((message, sender, reply) => {
  if (message?.type !== "iqcom-session-check" || !sender.url ||
      !["http://127.0.0.1:18766", "http://localhost:18766"].includes(new URL(sender.url).origin)) return;
  syncIqcomSession(true).then(reply, error => reply({error: error.message}));
  return true;
});
chrome.cookies.onChanged.addListener(({cookie}) => {
  if (["iq.com", "www.iq.com"].includes(cookie.domain.replace(/^\./, ""))) scheduleIqcomSync();
});
chrome.alarms.onAlarm.addListener(alarm => {
  if (alarm.name === "iqcom-session") syncIqcomSession().catch(() => {});
});
chrome.alarms.create("iqcom-session", {periodInMinutes: 0.5});
syncIqcomSession().catch(() => {});
