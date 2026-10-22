(function () {
  var host = location.hostname;
  if (!host && /^about:/.test(location.protocol)) {
    try { host = new URL(document.referrer).hostname; } catch (_) {}
  }
  if (!/(^|\.)iqiyi\.com$/i.test(host)) return;
  window.__iqiyiViTokenPending = true;
  var finished = false;
  var reloaded = false;
  var timer = setTimeout(function () { finish(); }, 4000);
  function finish(token) {
    if (token && token !== window.__iqiyiViToken) {
      window.__iqiyiViToken = token;
      if (!reloaded && window.__iqiyiViReload) {
        reloaded = true;
        window.__iqiyiViReload();
      }
    }
    if (finished) return;
    finished = true;
    clearTimeout(timer);
    window.__iqiyiViTokenPending = false;
  }
  fetch("http://127.0.0.1:18766/api/extension-token", {cache:"no-store", credentials:"omit"})
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (data) { finish(data && data.token); })
    .catch(function () { finish(); });
})();
