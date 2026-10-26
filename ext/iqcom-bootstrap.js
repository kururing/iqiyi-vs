(function () {
  var host = location.hostname;
  if (!host && /^about:/.test(location.protocol)) {
    try { host = new URL(document.referrer).hostname; } catch (_) {}
  }
  if (!/(^|\.)iqiyi\.com$/i.test(host)) return;
  function localRequest(message, signal) {
    return new Promise(function (resolve, reject) {
      if (signal && signal.aborted) return reject(signal.reason);
      var requestId = message.requestId || crypto.randomUUID();
      var settled = false;
      function finish(result, error) {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        if (signal) signal.removeEventListener("abort", abort);
        if (error) reject(error);
        else resolve(result);
      }
      function cancel() {
        try { chrome.runtime.sendMessage({type: "iqiyi-local-cancel", requestId: requestId}, function () { void chrome.runtime.lastError; }); }
        catch (_) {}
      }
      function abort() { cancel(); finish(null, signal.reason); }
      var timer = setTimeout(function () {
        cancel(); finish(null, Error("Không kết nối được app phụ đề. Kiểm tra app đang chạy."));
      }, 45000);
      if (signal) signal.addEventListener("abort", abort, {once:true});
      try {
        chrome.runtime.sendMessage(Object.assign({}, message, {type: "iqiyi-local-api", requestId: requestId}), function (result) {
          if (chrome.runtime.lastError || !result) finish(null, Error("Tải lại tiện ích và trang iQIYI để kết nối app phụ đề."));
          else if (result.error) finish(null, Error(result.error));
          else finish(result);
        });
      } catch (_) { finish(null, Error("Tải lại tiện ích và trang iQIYI để kết nối app phụ đề.")); }
    });
  }
  window.__iqiyiViLocalFetch = function (input, options) {
    options = options || {};
    var url = new URL(typeof input === "string" ? input : input.url, location.href);
    if (url.origin !== "http://127.0.0.1:18766") return Promise.reject(Error("Yêu cầu ngoài app phụ đề."));
    return localRequest({path: url.pathname + url.search, method: options.method || "GET", body: options.body}, options.signal)
      .then(function (result) { return new Response(result.body, {status: result.status, headers: result.headers}); });
  };
  window.addEventListener("message", function (event) {
    if (event.source !== window || (location.origin !== "null" && event.origin !== location.origin) ||
        !["iqiyi-local-request", "iqiyi-local-cancel"].includes(event.data?.type) ||
        typeof event.data.requestId !== "string" || event.data.requestId.length > 80) return;
    var requestId = event.data.requestId;
    if (event.data.type === "iqiyi-local-cancel") {
      try { chrome.runtime.sendMessage({type: "iqiyi-local-cancel", requestId: requestId}, function () { void chrome.runtime.lastError; }); }
      catch (_) {}
      return;
    }
    function reply(result) { window.postMessage({type: "iqiyi-local-result", requestId: requestId, result: result}, location.origin === "null" ? "*" : location.origin); }
    localRequest({requestId: requestId, path: event.data.path, method: event.data.method, body: event.data.body})
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
  function requestToken() {
    window.__iqiyiViLocalFetch("http://127.0.0.1:18766/api/extension-token")
      .then(function (r) { return r.ok ? r.json() : null; })
      .catch(function (error) {
        if (!finished) console.warn("[iQIYI Việt hóa]", error.message);
        return null;
      }).then(function (data) {
        var token = data && typeof data.token === "string" && data.token;
        finish(token);
        if (!token) setTimeout(requestToken, 15000);
      });
  }
  requestToken();
})();
