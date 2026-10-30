/* Only player routes on the fixed loopback service are exposed to iQIYI pages. */
const LOCAL_PLAYER_ORIGIN = "http://127.0.0.1:18766";
const LOCAL_PLAYER_ROUTES = {
  GET: new Set(["/health", "/api/extension-token", "/api/international-title", "/api/international-actor", "/api/international-search",
    "/api/official-subtitle-state", "/api/audio-state", "/api/audio-frame", "/subtitle.xml"]),
  POST: new Set(["/api/session", "/api/register", "/api/album/register", "/api/capture", "/api/localize-remaining", "/api/audio-playback", "/api/audio-settings", "/api/open-manager"])
};
const localPlayerRequests = new Map();

async function localPlayerRequest(message, signal) {
  const method = message.method || "GET";
  if (typeof message.path !== "string" || !message.path.startsWith("/") || message.path.length > 8192) {
    throw Error("Yêu cầu phụ đề không hợp lệ.");
  }
  const url = new URL(message.path, LOCAL_PLAYER_ORIGIN);
  if (url.origin !== LOCAL_PLAYER_ORIGIN || url.hash || !LOCAL_PLAYER_ROUTES[method]?.has(url.pathname) ||
      (method === "GET" && message.body != null) ||
      (message.body != null && (typeof message.body !== "string" || message.body.length > 2000000))) {
    throw Error("Yêu cầu phụ đề không được phép.");
  }
  if (["/api/localize-remaining", "/api/international-title", "/api/international-actor", "/api/international-search"].includes(url.pathname)) {
    return publicLocalizationRequest(url, message, signal);
  }
  if (url.pathname === "/api/audio-frame") {
    return {status:200,headers:{"Content-Type":"application/json"},body:JSON.stringify({url:chrome.runtime.getURL("audio-player.html")})};
  }
  if (["/api/audio-state", "/api/audio-settings", "/api/audio-playback"].includes(url.pathname)) {
    return url.pathname === "/api/audio-playback" ? audioJson({ok:true}) : browserAudioRequest(url, message);
  }
  const configResponse = await fetch(chrome.runtime.getURL("proxy-token.json"), {cache: "no-store", signal})
    .catch(error => {
      if (signal?.aborted) throw error;
      throw Error("Không đọc được cấu hình kết nối. Mở app quản lý và tải lại tiện ích Việt hóa.");
    });
  if (!configResponse.ok) throw Error("Mở lại app quản lý và tải lại tiện ích Việt hóa.");
  const config = await configResponse.json();
  if (!config.playerToken) throw Error("Mở lại app quản lý để cập nhật kết nối Chrome/Edge.");
  if (url.pathname === "/api/extension-token") {
    return {status: 200, headers: {"Content-Type": "application/json"}, body: JSON.stringify({token: config.playerToken})};
  }
  let response, body;
  try {
    response = await fetch(url.href, {
      method, body: method === "POST" ? message.body : undefined,
      headers: {"X-Iqiyi-Token": config.playerToken, ...(method === "POST" ? {"Content-Type": "application/json"} : {})},
      cache: "no-store", credentials: "omit", redirect: "error", signal
    });
    body = await response.text();
  } catch (error) {
    if (signal?.aborted) throw error;
    throw Error("Không kết nối được app phụ đề tại 127.0.0.1:18766. Mở app quản lý rồi thử lại.");
  }
  if (body.length > 8000000) throw Error("Dữ liệu phụ đề quá lớn.");
  return {status: response.status, headers: {"Content-Type": response.headers.get("Content-Type") || "text/plain"}, body};
}

chrome.runtime.onMessage.addListener((message, sender, reply) => {
  if (!["iqiyi-local-api", "iqiyi-local-cancel"].includes(message?.type)) return;
  try {
    const origin = new URL(sender.origin || sender.url);
    if (sender.id !== chrome.runtime.id || origin.protocol !== "https:" || origin.port ||
        !(origin.hostname === "iqiyi.com" || origin.hostname.endsWith(".iqiyi.com"))) return;
  } catch { return; }
  if (message.requestId != null && (typeof message.requestId !== "string" || message.requestId.length > 80)) return;
  // Scope cancellation to the originating document, including separate tabs/frames.
  const key = JSON.stringify([sender.tab?.id, sender.frameId, sender.documentId, message.requestId ?? crypto.randomUUID()]);
  if (message.type === "iqiyi-local-cancel") {
    localPlayerRequests.get(key)?.abort();
    reply({cancelled: true});
    return;
  }
  if (localPlayerRequests.has(key)) { reply({error: "Yêu cầu phụ đề đang được xử lý."}); return; }
  const controller = new AbortController();
  localPlayerRequests.set(key, controller);
  const timer = setTimeout(() => controller.abort(), 45000);
  localPlayerRequest(message, controller.signal).then(reply, error => reply({error: error.message}))
    .finally(() => { clearTimeout(timer); localPlayerRequests.delete(key); });
  return true;
});
