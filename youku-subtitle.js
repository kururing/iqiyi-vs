/* Translate live Youku captions and capture them in the shared subtitle manager. */
(function (root) {
  "use strict";
  if (!root) return;
  var VERSION = 3;
  if (root.__youkuViSubtitleVersion === VERSION) {
    if (root.__youkuViSubtitleRefresh) root.__youkuViSubtitleRefresh();
    return;
  }
  if (root.__youkuViSubtitleStop) root.__youkuViSubtitleStop();
  else if (root.__youkuViSubtitle) throw new Error("Restart Youku to update the legacy subtitle hook");
  root.__youkuViSubtitle = true;
  root.__youkuViSubtitleVersion = VERSION;

  var API = root.__youkuViApi || "http://127.0.0.1:18766";
  var TOKEN = root.__youkuViToken || "";
  var CACHE_KEY = "__youkuViSubtitleCacheV1";
  var CACHE = {}, QUEUE = [], PENDING = {}, ACTIVE = false;
  var REGISTERED = {}, REGISTERING = {}, CAPTURED = {}, captureContext = null, captureBuffer = [], captureTimer = 0;
  var captureUpload = Promise.resolve();
  var currentContext = null, current = "", lastSeen = 0, lastFullScan = 0, lastRegister = 0, showingManaged = false;
  var lastManagerFetch = 0, managerTrack = [], managerTrackKey = "", box;
  var stopped = false;
  try { CACHE = JSON.parse(localStorage.getItem(CACHE_KEY) || "{}"); } catch (_) {}

  function cjk(text) { return (String(text || "").match(/[\u3400-\u9fff]/g) || []).length; }
  function clean(text) {
    return String(text || "").replace(/<br\s*\/?\s*>/gi, "\n").replace(/<[^>]*>/g, "").replace(/&nbsp;/gi, " ").trim();
  }
  function hash(value) {
    var result = 2166136261;
    for (var i = 0; i < value.length; i++) { result ^= value.charCodeAt(i); result = Math.imul(result, 16777619); }
    return (result >>> 0).toString(36);
  }
  function pageContext() {
    var url;
    try { url = new URL(location.href); } catch (_) { return null; }
    var titleNode = document.querySelector("meta[property='og:title']");
    var title = clean(titleNode && titleNode.content || document.title || "Phim Youku")
      .replace(/\s*[-_|—]\s*(?:优酷|Youku).*$/i, "").trim() || "Phim Youku";
    var match = url.pathname.match(/id_([^/?#.&]+)/i);
    var videoId = match && match[1] || url.searchParams.get("vid") || url.searchParams.get("videoId") || "";
    var nativeInfo = null;
    if (url.protocol === "client:" && url.pathname === "/video" && root.videoPlayer && root.videoPlayer.getPlayerInfo) {
      try { nativeInfo = root.videoPlayer.getPlayerInfo(); } catch (_) {}
    }
    videoId = videoId || nativeInfo && (nativeInfo.vidEncoded || nativeInfo.vid) || "";
    if (!videoId) return null;
    videoId = String(videoId).replace(/[^A-Za-z0-9_-]/g, "-").slice(0, 90) || hash(url.href);
    var orderMatch = title.match(/第\s*(\d+)\s*集|(?:episode|ep)\s*(\d+)|s\d+\s*e(\d+)/i);
    var order = orderMatch ? Number(orderMatch[1] || orderMatch[2] || orderMatch[3]) : 0;
    var series = orderMatch ? title.replace(orderMatch[0], "").trim() : title;
    series = series.replace(/[\s:：,，|—-]+$/, "").trim() || title;
    var album = nativeInfo && (nativeInfo.showEncodedId || nativeInfo.showId) || "";
    ["showid", "albumid", "showId", "albumId"].some(function (key) {
      album = album || url.searchParams.get(key) || ""; return !!album;
    });
    var showMatch = url.pathname.match(/show\/id_([^/?#.&]+)/i);
    album = album || (showMatch && showMatch[1]) || ("title-" + hash(series.toLowerCase()));
    album = String(album).replace(/[^A-Za-z0-9_-]/g, "-").slice(0, 90) || hash(series);
    return {tvid: "yk-" + videoId, provider: "youku", title: title, albumTitle: series,
      albumId: "yk-" + album, order: order, pageUrl: url.origin + url.pathname};
  }
  function managerPost(route, payload) {
    if (!TOKEN || !root.fetch) return Promise.reject(new Error("manager unavailable"));
    return root.fetch(API + route, {method: "POST", headers: {"Content-Type": "application/json", "X-Iqiyi-Token": TOKEN},
      body: JSON.stringify(payload)}).then(function (response) {
      if (!response.ok) throw new Error("HTTP " + response.status);
      return response.json();
    });
  }
  function ensureRegistered(context) {
    if (!TOKEN || REGISTERED[context.tvid]) return Promise.resolve(true);
    if (REGISTERING[context.tvid]) return REGISTERING[context.tvid];
    REGISTERING[context.tvid] = managerPost("/api/register", context).then(function () {
      REGISTERED[context.tvid] = true; return true;
    }).catch(function () { return false; }).then(function (ok) {
      delete REGISTERING[context.tvid]; return ok;
    });
    return REGISTERING[context.tvid];
  }
  function formatTime(ms) {
    var hours = Math.floor(ms / 3600000), minutes = Math.floor(ms / 60000) % 60;
    var seconds = Math.floor(ms / 1000) % 60, millis = Math.floor(ms % 1000);
    return String(hours).padStart(2, "0") + ":" + String(minutes).padStart(2, "0") + ":" +
      String(seconds).padStart(2, "0") + "," + String(millis).padStart(3, "0");
  }
  function toSrt(cues) {
    return cues.map(function (cue, index) {
      return (index + 1) + "\n" + formatTime(cue.start) + " --> " + formatTime(cue.end) + "\n" + cue.text;
    }).join("\n\n") + "\n";
  }
  function normalizeCue(cue) {
    var text = clean(cue && cue.text), start = Math.max(0, Math.round(Number(cue && cue.start) || 0));
    var end = Math.round(Number(cue && cue.end) || 0);
    return text && text.length <= 1000 && end > start ? {start: start, end: end, text: text} : null;
  }
  function flushCapture() {
    if (captureTimer) { clearTimeout(captureTimer); captureTimer = 0; }
    if (!captureBuffer.length || !captureContext) return;
    var context = captureContext, batch = captureBuffer.splice(0, 200);
    var payload = {tvid: context.tvid, format: "srt", raw: toSrt(batch), append: true};
    captureUpload = captureUpload.then(function () { return ensureRegistered(context); }).then(function (ready) {
      if (!ready) throw new Error("manager unavailable");
      return managerPost("/api/capture", payload);
    }).catch(function () {
      if (captureContext && captureContext.tvid === context.tvid) {
        batch.forEach(function (cue) { CAPTURED[cue.start + ":" + cue.end + ":" + cue.text] = false; });
        captureBuffer = batch.concat(captureBuffer);
        if (!captureTimer) captureTimer = setTimeout(function () { captureTimer = 0; flushCapture(); }, 5000);
      }
    });
    if (captureBuffer.length && !captureTimer) captureTimer = setTimeout(function () { captureTimer = 0; flushCapture(); }, 250);
  }
  function queueCapture(context, cues) {
    if (!TOKEN || !context || !cues || !cues.length) return;
    if (captureContext && captureContext.tvid !== context.tvid) flushCapture();
    captureContext = context;
    cues.slice(0, 20000).forEach(function (rawCue) {
      var cue = normalizeCue(rawCue);
      if (!cue || !cjk(cue.text)) return;
      var key = cue.start + ":" + cue.end + ":" + cue.text;
      if (CAPTURED[key]) return;
      CAPTURED[key] = true;
      captureBuffer.push(cue);
    });
    if (captureBuffer.length >= 200) flushCapture();
    else if (captureBuffer.length && !captureTimer) captureTimer = setTimeout(function () { captureTimer = 0; flushCapture(); }, 1200);
  }
  function fullTrackCues() {
    var videos = document.querySelectorAll("video"), best = [], bestScore = 0;
    for (var i = 0; i < videos.length; i++) {
      var tracks = videos[i].textTracks;
      if (!tracks) continue;
      for (var j = 0; j < tracks.length; j++) {
        var source = tracks[j].cues, candidate = [], score = 0;
        if (!source || source.length > 20000) continue;
        for (var k = 0; k < source.length; k++) {
          var cue = normalizeCue({start: source[k].startTime * 1000, end: source[k].endTime * 1000, text: source[k].text});
          if (cue && cjk(cue.text)) { candidate.push(cue); score += cjk(cue.text); }
        }
        if (candidate.length && score > bestScore) { best = candidate; bestScore = score; }
      }
    }
    return best;
  }
  function activeCue() {
    var videos = document.querySelectorAll("video");
    for (var i = 0; i < videos.length; i++) {
      var tracks = videos[i].textTracks;
      if (!tracks) continue;
      for (var j = 0; j < tracks.length; j++) {
        var cues = tracks[j].activeCues;
        if (!cues) continue;
        for (var k = 0; k < cues.length; k++) {
          var cue = normalizeCue({start: cues[k].startTime * 1000, end: cues[k].endTime * 1000, text: cues[k].text});
          if (cue && cjk(cue.text)) return cue;
        }
      }
    }
    return null;
  }
  function visibleCue() {
    var cue = activeCue();
    if (cue) return cue;
    var nodes = document.querySelectorAll(".kui-subtitle-subtitle-container, .caption-main, [data-testid='subtitle']");
    var best = "";
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i], rect = el.getBoundingClientRect();
      if (!rect.width || rect.bottom < innerHeight * .55 || rect.top > innerHeight * .98) continue;
      var text = clean(el.innerText || el.textContent || "");
      if (text.length <= 180 && cjk(text) > cjk(best)) best = text;
    }
    if (!best) return null;
    var now = playbackTime();
    if (now === null) return {text: best};
    return normalizeCue({start: Math.max(0, Math.floor((now - 500) / 100) * 100), end: Math.ceil((now + 2200) / 100) * 100, text: best});
  }
  function playbackTime() {
    var video = document.querySelector("video");
    if (video && isFinite(video.currentTime)) return Math.max(0, video.currentTime * 1000);
    var player = root.videoPlayer;
    if (player && typeof player.getCurrentTime === "function") {
      try {
        var time = player.getCurrentTime();
        if (typeof time === "number" && isFinite(time)) return Math.max(0, time * 1000);
      } catch (_) {}
    }
    return null;
  }
  function parseSrt(raw) {
    var stamp = function (value) {
      var parts = value.trim().match(/^(\d+):(\d{2}):(\d{2})[,.](\d{3})$/);
      return parts ? ((Number(parts[1]) * 60 + Number(parts[2])) * 60 + Number(parts[3])) * 1000 + Number(parts[4]) : NaN;
    };
    return String(raw || "").replace(/^\uFEFF/, "").split(/\r?\n\s*\r?\n/).map(function (block) {
      var lines = block.trim().split(/\r?\n/), index = lines.findIndex(function (line) { return line.indexOf("-->") >= 0; });
      if (index < 0) return null;
      var times = lines[index].split("-->");
      return normalizeCue({start: stamp(times[0]), end: stamp(times[1]), text: lines.slice(index + 1).join("\n")});
    }).filter(Boolean);
  }
  function pollManagedTrack(context) {
    if (!TOKEN || !context || Date.now() - lastManagerFetch < 4000 || !root.fetch) return;
    lastManagerFetch = Date.now();
    root.fetch(API + "/api/file?tvid=" + encodeURIComponent(context.tvid), {headers: {"X-Iqiyi-Token": TOKEN}})
      .then(function (response) { return response.ok ? response.text() : ""; })
      .then(function (raw) {
        if (currentContext && currentContext.tvid === context.tvid) {
          managerTrack = parseSrt(raw); managerTrackKey = context.tvid;
        }
      }).catch(function () {});
  }
  function managedCueAt(time) {
    if (time === null || !managerTrack.length) return "";
    for (var i = 0; i < managerTrack.length; i++) {
      if (time >= managerTrack[i].start && time < managerTrack[i].end) return managerTrack[i].text;
    }
    return "";
  }
  function save() {
    try {
      var keys = Object.keys(CACHE);
      while (keys.length > 1200) delete CACHE[keys.shift()];
      localStorage.setItem(CACHE_KEY, JSON.stringify(CACHE));
    } catch (_) {}
  }
  function overlay() {
    if (box && box.isConnected) return box;
    box = document.createElement("div");
    box.id = "youku-vi-subtitle";
    box.setAttribute("aria-live", "polite");
    box.style.cssText = "position:fixed;z-index:2147483646;left:50%;bottom:11%;transform:translateX(-50%);" +
      "max-width:86vw;color:#fff;font:700 clamp(24px,5vw,48px)/1.25 Arial,Helvetica,sans-serif;text-align:center;" +
      "-webkit-text-stroke:1.2px #111;paint-order:stroke fill;text-shadow:0 2px 4px #000;" +
      "pointer-events:none;white-space:pre-line;display:none";
    (document.body || document.documentElement).appendChild(box);
    return box;
  }
  function show(text) {
    if (stopped) return;
    var target = overlay();
    target.textContent = text;
    target.style.display = text ? "block" : "none";
  }
  function translate(text) {
    text = String(text || "").trim();
    if (!text || cjk(text) < 1 || text.length > 180 || PENDING[text]) return;
    if (CACHE[text]) { if (text === current) show(CACHE[text]); return; }
    PENDING[text] = true;
    QUEUE.push(text);
    pump();
  }
  function pump() {
    if (ACTIVE || !QUEUE.length || !root.fetch) return;
    ACTIVE = true;
    var batch = [], url = "https://clients5.google.com/translate_a/t?client=dict-chrome-ex&sl=zh-CN&tl=vi";
    while (QUEUE.length && batch.length < 8) {
      var next = QUEUE[0], part = "&q=" + encodeURIComponent(next);
      if (batch.length && url.length + part.length > 5000) break;
      batch.push(QUEUE.shift()); url += part;
    }
    Promise.race([root.fetch(url), new Promise(function (_, reject) {
      setTimeout(function () { reject(new Error("timeout")); }, 8000);
    })]).then(function (response) {
      if (!response.ok) throw new Error("HTTP " + response.status);
      return response.json();
    }).then(function (data) {
      batch.forEach(function (source, index) {
        var result = data && data[index];
        if (result && !cjk(result)) CACHE[source] = result;
        delete PENDING[source];
        if (source === current && CACHE[source]) show(CACHE[source]);
      });
      save();
    }).catch(function () {
      batch.forEach(function (source) { delete PENDING[source]; });
    }).then(function () { ACTIVE = false; setTimeout(pump, 250); });
  }
  function tick() {
    var context = pageContext();
    if (!context) {
      if (currentContext) {
        flushCapture(); currentContext = null; current = ""; managerTrack = []; showingManaged = false; show("");
      }
      return;
    }
    if (!currentContext || context.tvid !== currentContext.tvid) {
      flushCapture();
      currentContext = context; current = ""; managerTrack = []; managerTrackKey = context.tvid; showingManaged = false; show("");
      captureContext = context; captureBuffer = []; CAPTURED = {}; lastRegister = 0; lastManagerFetch = 0;
    } else currentContext = context;
    if (Date.now() - lastRegister > 12000) {
      lastRegister = Date.now(); ensureRegistered(context);
    }
    if (Date.now() - lastFullScan > 2500) {
      lastFullScan = Date.now();
      var full = fullTrackCues();
      if (full.length) queueCapture(context, full);
    }
    pollManagedTrack(context);
    var cue = visibleCue(), managed = managedCueAt(playbackTime());
    if (cue) {
      lastSeen = Date.now();
      if (cue.text !== current) {
        current = cue.text;
        queueCapture(context, [cue]);
        if (CACHE[cue.text]) show(CACHE[cue.text]);
        else { show(""); translate(cue.text); }
      }
    }
    if (managed) { lastSeen = Date.now(); showingManaged = true; show(managed); }
    else if (showingManaged) {
      showingManaged = false;
      if (cue && CACHE[cue.text]) show(CACHE[cue.text]);
      else { show(""); if (cue) translate(cue.text); }
    } else if (!cue && Date.now() - lastSeen > 700 && box) { current = ""; show(""); }
  }
  root.__youkuViSubtitleStatus = function () {
    return {visible: !!(box && box.style.display !== "none"), cached: Object.keys(CACHE).length,
      captured: Object.keys(CAPTURED).length, managed: managerTrack.length, registered: !!(currentContext && REGISTERED[currentContext.tvid])};
  };
  root.__youkuViSubtitleRefresh = function () {
    if (box) { var text = box.textContent; box.remove(); box = null; show(text); }
  };
  var tickTimer = setInterval(tick, 250);
  root.__youkuViSubtitleStop = function () {
    stopped = true;
    clearInterval(tickTimer);
    flushCapture();
    if (box) box.remove();
    root.__youkuViSubtitle = false;
    root.__youkuViSubtitleVersion = 0;
  };
})(window);
