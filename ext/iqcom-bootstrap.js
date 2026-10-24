(function () {
  var host = location.hostname;
  if (!host && /^about:/.test(location.protocol)) {
    try { host = new URL(document.referrer).hostname; } catch (_) {}
  }
  if (!/(^|\.)iqiyi\.com$/i.test(host)) return;
  function localRequest(message) {
    return new Promise(function (resolve, reject) {
      try {
        chrome.runtime.sendMessage(Object.assign({}, message, {type: "iqiyi-local-api"}), function (result) {
          if (chrome.runtime.lastError || !result) reject(Error("Tải lại tiện ích và trang iQIYI để kết nối app phụ đề."));
          else if (result.error) reject(Error(result.error));
          else resolve(result);
        });
      } catch (_) { reject(Error("Tải lại tiện ích và trang iQIYI để kết nối app phụ đề.")); }
    });
  }
  window.__iqiyiViLocalFetch = function (input, options) {
    options = options || {};
    var url = new URL(typeof input === "string" ? input : input.url, location.href);
    if (url.origin !== "http://127.0.0.1:18766") return Promise.reject(Error("Yêu cầu ngoài app phụ đề."));
    return localRequest({path: url.pathname + url.search, method: options.method || "GET", body: options.body})
      .then(function (result) { return new Response(result.body, {status: result.status, headers: result.headers}); });
  };
  window.addEventListener("message", function (event) {
    if (event.source !== window || (location.origin !== "null" && event.origin !== location.origin) || event.data?.type !== "iqiyi-local-request" ||
        typeof event.data.requestId !== "string" || event.data.requestId.length > 80) return;
    var requestId = event.data.requestId;
    function reply(result) { window.postMessage({type: "iqiyi-local-result", requestId: requestId, result: result}, location.origin === "null" ? "*" : location.origin); }
    localRequest({path: event.data.path, method: event.data.method, body: event.data.body})
      .then(reply, function (error) { reply({error: error.message}); });
  });
  window.__iqiyiViTokenPending = true;
  var finished = false;
  var timer = setTimeout(function () { finish(); }, 4000);
  function finish(token) {
    var changed = false;
    if (token && token !== window.__iqiyiViToken) {
      window.__iqiyiViToken = token;
      changed = true;
    }
    if (!finished) {
      finished = true;
      clearTimeout(timer);
      window.__iqiyiViTokenPending = false;
      changed = true;
    }
    if (changed && window.__iqiyiViReload) window.__iqiyiViReload();
  }
  window.__iqiyiViLocalFetch("http://127.0.0.1:18766/api/extension-token")
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (data) { finish(data && data.token); })
    .catch(function (error) { console.warn("[iQIYI Việt hóa]", error.message); finish(); });
})();
