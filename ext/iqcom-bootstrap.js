(function () {
  var host = location.hostname;
  if (!host && /^about:/.test(location.protocol)) {
    try { host = new URL(document.referrer).hostname; } catch {}
  }
  if (!/(^|\.)iqiyi\.com$/i.test(host)) return;
  window.__iqiyiViPublicApi = true;
  var bridgeExpired = false;
  window.__iqiyiViBridgeExpired = false;
  function contextAlive() {
    try { return !!chrome.runtime.id; } catch { return false; }
  }
  function bridgeError(cause) {
    if (bridgeExpired || !contextAlive() || /context.*invalidated/i.test(String(cause && cause.message || cause || ""))) {
      if (!bridgeExpired) {
        bridgeExpired = true;
        window.__iqiyiViBridgeExpired = true;
        window.__iqiyiViPublicApi = false;
        window.__iqiyiViTokenPending = false;
        if (window.__iqiyiViPauseNetwork) window.__iqiyiViPauseNetwork();
      }
      return Object.assign(Error("Tiện ích đã được tải lại. Tải lại trang iQIYI để tiếp tục Việt hóa tự động."), {code:"EXTENSION_CONTEXT_INVALIDATED"});
    }
    return Object.assign(Error("Không kết nối được tiện ích Việt hóa. Tải lại tiện ích và trang iQIYI."), {code:"EXTENSION_BRIDGE_UNAVAILABLE"});
  }
  function localRequest(message, signal) {
    return new Promise(function (resolve, reject) {
      if (signal && signal.aborted) return reject(signal.reason);
      if (bridgeExpired || !contextAlive()) return reject(bridgeError());
      var requestId = message.requestId || crypto.randomUUID();
      var settled = false, attempts = 0, retryTimer;
      function finish(result, error) {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        clearTimeout(retryTimer);
        if (signal) signal.removeEventListener("abort", abort);
        if (error) reject(error);
        else resolve(result);
      }
      function cancel() {
        if (bridgeExpired || !contextAlive()) return;
        try { chrome.runtime.sendMessage({type: "iqiyi-local-cancel", requestId: requestId}, function () { void chrome.runtime.lastError; }); }
        catch {}
      }
      function abort() { cancel(); finish(null, signal.reason); }
      var timer = setTimeout(function () {
        cancel(); finish(null, Error("Không kết nối được app phụ đề. Kiểm tra app đang chạy."));
      }, 45000);
      if (signal) signal.addEventListener("abort", abort, {once:true});
      function failed(cause) {
        if (settled) return;
        var error = bridgeError(cause);
        if (error.code !== "EXTENSION_CONTEXT_INVALIDATED" && attempts++ < 2) {
          retryTimer = setTimeout(send, 300 * attempts);
        } else finish(null, error);
      }
      function send() {
        if (settled) return;
        if (bridgeExpired || !contextAlive()) return failed();
        try {
          chrome.runtime.sendMessage(Object.assign({}, message, {type: "iqiyi-local-api", requestId: requestId}), function (result) {
            var error = chrome.runtime.lastError;
            if (error || !result) failed(error);
            else if (result.error) finish(null, Object.assign(Error(result.error), {code:result.code}));
            else finish(result);
          });
        } catch (error) { failed(error); }
      }
      send();
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
      catch {}
      return;
    }
    function reply(result) { window.postMessage({type: "iqiyi-local-result", requestId: requestId, result: result}, location.origin === "null" ? "*" : location.origin); }
    localRequest({requestId: requestId, path: event.data.path, method: event.data.method, body: event.data.body})
      .then(reply, function (error) { reply({error: error.message, code:error.code}); });
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
      .catch(function () { return null; }).then(function (data) {
        var token = data && typeof data.token === "string" && data.token;
        finish(token);
        if (!token && !bridgeExpired) setTimeout(requestToken, 15000);
      });
  }
  requestToken();
})();
