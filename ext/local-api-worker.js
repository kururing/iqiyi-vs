/* Only player routes on the fixed loopback service are exposed to iQIYI pages. */
const LOCAL_PLAYER_ORIGIN = "http://127.0.0.1:18766";
const LOCAL_PLAYER_ROUTES = {
  GET: new Set(["/health", "/api/extension-token", "/api/international-title", "/api/international-actor",
    "/api/translation-state", "/api/file", "/subtitle.xml"]),
  POST: new Set(["/api/session", "/api/register", "/api/album/register", "/api/capture"])
};

async function localPlayerRequest(message) {
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
  const configResponse = await fetch(chrome.runtime.getURL("proxy-token.json"), {cache: "no-store"});
  if (!configResponse.ok) throw Error("Mở lại app quản lý và tải lại tiện ích Việt hóa.");
  const config = await configResponse.json();
  if (!config.playerToken) throw Error("Mở lại app quản lý để cập nhật kết nối Chrome/Edge.");
  if (url.pathname === "/api/extension-token") {
    return {status: 200, headers: {"Content-Type": "application/json"}, body: JSON.stringify({token: config.playerToken})};
  }
  const response = await fetch(url.href, {
    method, body: method === "POST" ? message.body : undefined,
    headers: {"X-Iqiyi-Token": config.playerToken, ...(method === "POST" ? {"Content-Type": "application/json"} : {})},
    cache: "no-store", credentials: "omit", redirect: "error", signal: AbortSignal.timeout(45000)
  });
  const body = await response.text();
  if (body.length > 8000000) throw Error("Dữ liệu phụ đề quá lớn.");
  return {status: response.status, headers: {"Content-Type": response.headers.get("Content-Type") || "text/plain"}, body};
}

chrome.runtime.onMessage.addListener((message, sender, reply) => {
  if (message?.type !== "iqiyi-local-api") return;
  try {
    const origin = new URL(sender.origin || sender.url);
    if (sender.id !== chrome.runtime.id || origin.protocol !== "https:" || origin.port ||
        !(origin.hostname === "iqiyi.com" || origin.hostname.endsWith(".iqiyi.com"))) return;
  } catch (_) { return; }
  localPlayerRequest(message).then(reply, error => reply({error: error.message}));
  return true;
});
