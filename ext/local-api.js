/* MAIN-world player code uses the existing extension permission through an isolated bridge. */
(function () {
  const pending = new Map();
  window.addEventListener("message", event => {
    if (event.source !== window || (location.origin !== "null" && event.origin !== location.origin) || event.data?.type !== "iqiyi-local-result") return;
    const entry = pending.get(event.data.requestId);
    if (!entry) return;
    entry.cleanup();
    const result = event.data.result;
    if (!result || result.error) entry.reject(Object.assign(Error(result?.error || "Không kết nối được app phụ đề."), {code:result?.code}));
    else {
      try { entry.resolve(new Response(result.body, {status: result.status, headers: result.headers})); }
      catch (error) { entry.reject(error); }
    }
  });
  window.__iqiyiViLocalFetch = function (input, options = {}) {
    const url = new URL(typeof input === "string" ? input : input.url, location.href);
    if (url.origin !== "http://127.0.0.1:18766") return Promise.reject(Error("Yêu cầu ngoài app phụ đề."));
    return new Promise((resolve, reject) => {
      const signal = options.signal;
      if (signal?.aborted) return reject(signal.reason);
      const requestId = crypto.randomUUID();
      const target = location.origin === "null" ? "*" : location.origin;
      let dispatchTimer;
      const cleanup = () => {
        pending.delete(requestId);
        clearTimeout(timer);
        clearTimeout(dispatchTimer);
        signal?.removeEventListener("abort", abort);
      };
      const abort = () => {
        cleanup();
        window.postMessage({type: "iqiyi-local-cancel", requestId}, target);
        reject(signal.reason);
      };
      const timer = setTimeout(() => {
        cleanup();
        window.postMessage({type: "iqiyi-local-cancel", requestId}, target);
        reject(Error("Không kết nối được app phụ đề. Kiểm tra app đang chạy và tải lại tiện ích."));
      }, 45000);
      pending.set(requestId, {resolve, reject, cleanup});
      signal?.addEventListener("abort", abort, {once: true});
      // Let all document_start listeners register before sending the first token request.
      dispatchTimer = setTimeout(() => window.postMessage({type: "iqiyi-local-request", requestId,
        path: url.pathname + url.search, method: options.method || "GET", body: options.body}, target), 0);
    });
  };
})();
