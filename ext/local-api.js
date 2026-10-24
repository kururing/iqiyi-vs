/* MAIN-world player code uses the existing extension permission through an isolated bridge. */
(function () {
  const pending = new Map();
  window.addEventListener("message", event => {
    if (event.source !== window || (location.origin !== "null" && event.origin !== location.origin) || event.data?.type !== "iqiyi-local-result") return;
    const entry = pending.get(event.data.requestId);
    if (!entry) return;
    pending.delete(event.data.requestId);
    clearTimeout(entry.timer);
    const result = event.data.result;
    if (!result || result.error) entry.reject(Error(result?.error || "Không kết nối được app phụ đề."));
    else entry.resolve(new Response(result.body, {status: result.status, headers: result.headers}));
  });
  window.__iqiyiViLocalFetch = function (input, options = {}) {
    const url = new URL(typeof input === "string" ? input : input.url, location.href);
    if (url.origin !== "http://127.0.0.1:18766") return Promise.reject(Error("Yêu cầu ngoài app phụ đề."));
    return new Promise((resolve, reject) => {
      const requestId = crypto.randomUUID();
      const timer = setTimeout(() => {
        pending.delete(requestId);
        reject(Error("Không kết nối được app phụ đề. Kiểm tra app đang chạy và tải lại tiện ích."));
      }, 45000);
      pending.set(requestId, {resolve, reject, timer});
      // Let all document_start listeners register before sending the first token request.
      setTimeout(() => window.postMessage({type: "iqiyi-local-request", requestId,
        path: url.pathname + url.search, method: options.method || "GET", body: options.body}, location.origin === "null" ? "*" : location.origin), 0);
    });
  };
})();
