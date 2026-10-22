(function () {
  var host = location.hostname;
  if (!host && /^about:/.test(location.protocol)) {
    try { host = new URL(document.referrer).hostname; } catch (_) {}
  }
  if (!/(^|\.)iqiyi\.com$/i.test(host)) return;
  if (typeof chrome !== "undefined" && chrome.runtime && chrome.runtime.sendMessage) {
    window.__iqiyiViTranslate = function (texts) {
      return chrome.runtime.sendMessage({type:"iqiyi-vi-translate", texts:texts}).then(function (reply) {
        if (!reply || reply.error) throw new Error(reply && reply.error || "No translation response");
        return reply.translations;
      });
    };
  }
  window.__iqiyiViTokenPending = true;
  var timer = setTimeout(done, 4000);
  function done() {
    clearTimeout(timer);
    window.__iqiyiViTokenPending = false;
    if (window.__iqiyiViReload) window.__iqiyiViReload();
  }
  fetch("http://127.0.0.1:18766/api/extension-token", {cache:"no-store", credentials:"omit"})
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (data) { if (data && data.token) window.__iqiyiViToken = data.token; done(); })
    .catch(done);
})();
