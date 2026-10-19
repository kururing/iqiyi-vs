/* Player subtitle hooks for iQIYI and Youku in one file; the router at the bottom picks the provider.
   - iQIYI: register player-provided subtitle tracks and use translated local tracks.
   - Youku: translate live captions, capture them in the shared subtitle manager and apply Youku layout CSS. */
(function (root) {
  "use strict";

  function iqiyiSubtitleHook() {
    var SIDE = "http://127.0.0.1:18766";
    var TOKEN = root && root.__iqiyiViToken || "";
    var nativeFetch = root && root.fetch ? root.fetch.bind(root) : null;
    var TRACK = /^(xml|srt|webvtt|vtt)$/;
    var VI_LID = 23;
    var VI_NAME = "Tiếng Việt (AI)";
    var titles = new Map();
    var albumIds = new Map();
    var registered = new Set();
    var sourceByUrl = new Map();
    var captured = new Set();
    var capturing = new Map();
    var queued = new Set();
    var listPosted = new Set();
    var posting = new Map();
    var registrations = new Map();
    var translationStates = new Map();
    var activeViTvid = "";
    var activeViDisabled = true;
    var disabledOptionState = new WeakMap();
    var menuObserver = null;
    var menuScanTimer = null;

    function syncPlayerSession() {
      if (!root || !TOKEN || syncPlayerSession.pending) return;
      var account = root.QySdk && root.QySdk.Account;
      if (!account || !account.getLoginInfo) return;
      syncPlayerSession.pending = true;
      var result;
      try { result = account.getLoginInfo(); } catch (_) { syncPlayerSession.pending = false; return; }
      Promise.resolve(result && result.cache || result).then(function (info) {
        if (!info || typeof info !== "object" || !Object.keys(info).length) return;
        var appService = root.QySdk.AppService;
        var system = appService && appService.getSystemInfo ? appService.getSystemInfo() : null;
        system = system && system.cache || {};
        var auth = String(info.authcookie || ""), uid = String(info.uid || "");
        var types = info.vip_types || info.vipTypes || [];
        if (typeof types === "string") types = types.split(",");
        var session = {authcookie: auth, uid: uid,
          vipTypes: Array.isArray(types) ? types.map(String) : [],
          deviceId: String(system.deviceId || system.clientid || ""),
          dfp: String(system.dfp || "")};
        var signature = JSON.stringify(session), now = Date.now();
        if (signature === syncPlayerSession.signature && now - syncPlayerSession.sent < 30000) return;
        return post("/api/session", session).then(function () {
          syncPlayerSession.signature = signature;
          syncPlayerSession.sent = now;
        });
      }).catch(function () {}).then(function () { syncPlayerSession.pending = false; });
    }

    function post(route, data) {
      if (!nativeFetch || !TOKEN) return Promise.reject(new Error("Subtitle manager token is unavailable"));
      return nativeFetch(SIDE + route, {method:"POST",
        headers:{"Content-Type":"application/json", "X-Iqiyi-Token":TOKEN}, body:JSON.stringify(data)})
        .then(function (response) { if (!response.ok) throw new Error("Subtitle manager HTTP " + response.status); });
    }
    function getTranslationState(tvid) {
      if (!nativeFetch || !TOKEN || !tvid) return Promise.resolve({available:false, translating:true});
      var cached = translationStates.get(tvid);
      if (cached && cached.value && cached.expires > Date.now()) return Promise.resolve(cached.value);
      if (cached && cached.promise) return cached.promise;
      var url = SIDE + "/api/translation-state?tvid=" + encodeURIComponent(tvid) + "&token=" + encodeURIComponent(TOKEN);
      var job = nativeFetch(url).then(function (response) {
        if (!response.ok) throw new Error("Translation status unavailable");
        return response.json();
      }).then(function (state) {
        var value = {available:state.available === true, translating:state.translating === true};
        translationStates.set(tvid, {value:value, expires:Date.now() + 500});
        return value;
      }).catch(function () {
        var value = {available:false, translating:true};
        translationStates.set(tvid, {value:value, expires:Date.now() + 1000});
        return value;
      });
      translationStates.set(tvid, {promise:job, expires:0});
      return job;
    }
    function isViLabel(value) {
      return /^(?:tiếng\s*việt(?:\s*\(ai\))?|vietnamese(?:\s*\(ai\))?|越南语|越南文)$/i.test(
        String(value || "").replace(/\s+/g, " ").trim());
    }
    function subtitleOptionElement(labelNode) {
      var option = labelNode;
      for (var depth = 0; depth < 4 && option.parentElement && option.parentElement !== root.document.body; depth++) {
        var role = option.getAttribute("role") || "";
        var className = typeof option.className === "string" ? option.className : "";
        if (/^(button|option|menuitem)$/i.test(role) || /^(BUTTON|LI)$/.test(option.tagName) ||
            /(?:^|[-_ ])(?:item|option|track)(?:$|[-_ ])/i.test(className) || option.hasAttribute("tabindex")) break;
        option = option.parentElement;
      }
      return option;
    }
    function optionForTarget(target) {
      var node = target && (target.nodeType === 1 ? target : target.parentElement);
      while (node && node !== root.document.body) {
        var label = String(node.innerText || node.textContent || "").replace(/\s+/g, " ").trim();
        if (node.nodeType === 1 && isViLabel(label)) return subtitleOptionElement(node);
        node = node.parentElement;
      }
      return null;
    }
    function applyDisabledOption(option) {
      if (!option) return;
      var previous = disabledOptionState.get(option);
      if (activeViDisabled) {
        if (!previous) {
          previous = {aria:option.getAttribute("aria-disabled"), disabled:"disabled" in option ? option.disabled : null,
            opacity:option.style.opacity, cursor:option.style.cursor};
          disabledOptionState.set(option, previous);
        }
        option.setAttribute("aria-disabled", "true");
        if (previous.disabled !== null) option.disabled = true;
        option.style.opacity = "0.45";
        option.style.cursor = "not-allowed";
        return;
      }
      if (!previous) return;
      if (previous.aria === null) option.removeAttribute("aria-disabled");
      else option.setAttribute("aria-disabled", previous.aria);
      if (previous.disabled !== null) option.disabled = previous.disabled;
      option.style.opacity = previous.opacity;
      option.style.cursor = previous.cursor;
      disabledOptionState.delete(option);
    }
    function scanSubtitleMenu() {
      menuScanTimer = null;
      if (!root || !root.document || !root.document.querySelectorAll) return;
      var candidates = root.document.querySelectorAll("button,[role],li,[class],span,div");
      candidates.forEach(function (node) {
        var label = String(node.innerText || node.textContent || "").replace(/\s+/g, " ").trim();
        if (!isViLabel(label)) return;
        applyDisabledOption(subtitleOptionElement(node));
      });
    }
    function scheduleSubtitleMenuScan() {
      if (menuScanTimer !== null || !root || !root.setTimeout) return;
      menuScanTimer = root.setTimeout(scanSubtitleMenu, 80);
    }
    function setActiveViTrack(tvid) {
      if (!tvid || !root || !root.document) return;
      activeViTvid = String(tvid);
      activeViDisabled = true;
      scheduleSubtitleMenuScan();
      getTranslationState(activeViTvid).then(function (state) {
        if (activeViTvid !== String(tvid)) return;
        activeViDisabled = !state.available || state.translating;
        scheduleSubtitleMenuScan();
      });
    }
    function refreshActiveViTrack() {
      if (!activeViTvid) return;
      var tvid = activeViTvid;
      getTranslationState(tvid).then(function (state) {
        if (activeViTvid !== tvid) return;
        activeViDisabled = !state.available || state.translating;
        scheduleSubtitleMenuScan();
      });
    }
    function clearActiveViTrack(tvid) {
      if (activeViTvid !== String(tvid)) return;
      activeViTvid = "";
      activeViDisabled = false;
      scheduleSubtitleMenuScan();
    }
    function installSubtitleMenuGuard() {
      var doc = root && root.document;
      if (!doc || !doc.addEventListener || doc.__iqiyiViMenuGuard) return;
      doc.__iqiyiViMenuGuard = true;
      function blockUnavailableSelection(event) {
        if (!activeViDisabled || !activeViTvid) return;
        if (event.type === "keydown" && event.key !== "Enter" && event.key !== " ") return;
        if (!optionForTarget(event.target)) return;
        event.preventDefault();
        event.stopPropagation();
        if (event.stopImmediatePropagation) event.stopImmediatePropagation();
      }
      ["pointerdown", "click", "keydown"].forEach(function (type) {
        doc.addEventListener(type, blockUnavailableSelection, true);
      });
      if (root.MutationObserver && doc.documentElement) {
        menuObserver = new root.MutationObserver(scheduleSubtitleMenuScan);
        menuObserver.observe(doc.documentElement, {childList:true, subtree:true});
      }
      if (root.setInterval) root.setInterval(refreshActiveViTrack, 1000);
    }
    function installSubtitleStyle() {
      var doc = root.document;
      if (!doc) return;
      function addStyle() {
        if (!doc.documentElement) return;
        var style = doc.getElementById("iqiyi-vi-subtitle-css") || doc.createElement("style");
        style.id = "iqiyi-vi-subtitle-css";
        style.textContent =
          'img[src*="/watermark_rightTop"],img[src*="/watermark_rightBottom"]{display:none!important;}' +
          '#pcaSubtitleContainer,#pcaSubtitleContainer *,.caption-main,.caption-main *{' +
          'font-family:Arial,Helvetica,sans-serif!important;font-weight:700!important;color:#fff!important;' +
          '-webkit-text-stroke:1.2px #111!important;paint-order:stroke fill;' +
          'text-shadow:0 1px 1px #111,1px 0 1px #111,-1px 0 1px #111,0 -1px 1px #111,0 2px 4px #000!important;}' +
          'video::cue{font-family:Arial,Helvetica,sans-serif;font-weight:700;color:#fff;background:transparent;' +
          'text-shadow:0 1px 1px #111,1px 0 1px #111,-1px 0 1px #111,0 -1px 1px #111,0 2px 4px #000;}';
        if (!style.parentNode) (doc.head || doc.documentElement).appendChild(style);
      }
      if (doc.documentElement) addStyle();
      else doc.addEventListener("DOMContentLoaded", addStyle, {once:true});
    }
    function postOnce(key, route, data, completed) {
      if (completed.has(key)) return Promise.resolve(true);
      var pendingKey = route + ":" + key;
      if (posting.has(pendingKey)) return posting.get(pendingKey);
      function attempt(retries) {
        return post(route, data).catch(function (error) {
          if (!root || !root.setTimeout || retries >= 3) throw error;
          return new Promise(function (resolve) { root.setTimeout(resolve, 500 * Math.pow(2, retries)); })
            .then(function () { return attempt(retries + 1); });
        });
      }
      var job = attempt(0).then(function () { completed.add(key); return true; }, function () { return false; })
        .then(function (ok) { posting.delete(pendingKey); return ok; });
      posting.set(pendingKey, job);
      return job;
    }

    function decode(value) {
      if (typeof value !== "string" || !/^[\s]*[\[{\"]/.test(value)) return value;
      try { return JSON.parse(value); } catch (_) { return value; }
    }
    function identity(value, inherited) {
      var id = value.tvId || value.tvid || value.entityId || value.entity_id || "";
      var albumId = value.albumId || value.album_id || "";
      var candidates = [
        value.entityTitle, value.display_name_v2, value.display_name,
        value.tvName, value.tv_name, value.albumName, value.album_name,
        value.videoName, value.video_name, value.entityName, value.entity_name,
        value.title, value.name
      ].filter(function (item) { return typeof item === "string" && item; });
      var title = candidates.find(function (item) { return /[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]/.test(item); }) ||
        candidates[0] || (id && (value.title || value.name)) || "";
      if (id && (title || albumId)) {
        if (titles.size >= 64 && !titles.has(String(id))) {
          var oldest = titles.keys().next().value;
          titles.delete(oldest);
          albumIds.delete(oldest);
        }
        if (title) titles.set(String(id), String(title));
        if (albumId) albumIds.set(String(id), String(albumId));
      }
      var key = String(id || inherited.tvid || "");
      var sameId = !id || key === inherited.tvid;
      return {
        tvid: key,
        title: String(title || titles.get(key) || (sameId ? inherited.title : "") || ""),
        albumId: String(albumId || albumIds.get(key) || (sameId ? inherited.albumId : "") || ""),
        prefix: String(value.prefix || value.dstl || inherited.prefix || "")
      };
    }
    function trackUrl(item) {
      return Object.keys(item).find(function (key) {
        return TRACK.test(key) && typeof item[key] === "string" && item[key] &&
          (/^https?:\/\//i.test(item[key]) || /^\/\//.test(item[key]) || /^\//.test(item[key]) ||
            /\.(xml|srt|vtt|webvtt)(?:[?#]|$)/i.test(item[key]));
      }) || "";
    }
    function absolute(url, prefix) {
      if (/^https?:\/\//i.test(url)) return url;
      var proto = (prefix.match(/^https?:/i) || ["https:"])[0];
      if (url.indexOf("//") === 0) return proto + url;
      var origin = (prefix.match(/^https?:\/\/[^/]+/i) || ["https://meta.video.iqiyi.com"])[0];
      if (url.charAt(0) === "/") return origin + url;
      return prefix.replace(/\/?$/, "/") + url.replace(/^\//, "");
    }
    function isTrackArray(items) {
      return items.some(function (item) {
        return item && typeof item === "object" && !Array.isArray(item) &&
          item.lid != null && !!trackUrl(item);
      });
    }
    function prepareTracks(items, context) {
      var chinese = items.find(function (item) { return item && String(item.lid) === "1"; });
      var preferred = chinese || items.find(function (item) { return item && String(item.lid) !== String(VI_LID) && trackUrl(item); });
      var sourceTracks = items.filter(function (item) { return item && trackUrl(item) &&
        !(typeof item.xml === "string" && item.xml.indexOf(SIDE + "/subtitle.xml?") === 0); }).map(function (item) {
        var key = trackUrl(item);
        var url = absolute(item[key], context.prefix);
        if (item === preferred) sourceByUrl.set(url, {tvid:context.tvid, format:key});
        return {lid:String(item.lid || ""), name:String(item.name || item.title || ""), url:url, format:key};
      });
      if (context.tvid) {
        var registration = {tvid:context.tvid,title:context.title,albumId:context.albumId,tracks:sourceTracks};
        registrations.set(context.tvid, postOnce(JSON.stringify(registration), "/api/register", registration, registered));
      }
      var viTrack = {
        lid: VI_LID,
        pre: 0,
        name: VI_NAME,
        title: VI_NAME,
        xml: SIDE + "/subtitle.xml?tvid=" + encodeURIComponent(context.tvid) + "&token=" + encodeURIComponent(TOKEN)
      };
      var output = items.filter(function (item) { return !item || typeof item.xml !== "string" || item.xml.indexOf(SIDE + "/subtitle.xml?") !== 0; })
        .map(function (item) {
          if (!item || typeof item !== "object") return item;
          var copy = Object.assign({}, item);
          Object.keys(copy).forEach(function (key) {
            if (TRACK.test(key) && typeof copy[key] === "string" && copy[key]) copy[key] = absolute(copy[key], context.prefix);
          });
          return copy;
        });
      if (!context.tvid) return output;
      if (output.some(function (item) { return item && String(item.lid) === String(VI_LID); })) {
        clearActiveViTrack(context.tvid);
        return output;
      }
      var translation = translationStates.get(String(context.tvid));
      if (!translation || !translation.value) {
        // Prime the status cache; keep the track non-default until availability is confirmed.
        getTranslationState(String(context.tvid));
      }
      var available = !!(translation && translation.value && translation.value.available);
      // Keep a disabled placeholder in the player track list so subtitles translated
      // after playback starts can become selectable without reloading the episode.
      setActiveViTrack(context.tvid);
      var index = output.findIndex(function (item) { return item && String(item.lid) === "1"; });
      if (available) viTrack.main = 1;
      output.splice(index < 0 ? output.length : index + 1, 0, viTrack);
      return output;
    }
    function trackTvids(body) {
      var found = new Set();
      function scan(value, context, depth) {
        if (depth > 32) return;
        var parsed = decode(value);
        if (parsed !== value) { scan(parsed, context, depth + 1); return; }
        if (!value || typeof value !== "object") return;
        if (Array.isArray(value)) {
          if (isTrackArray(value) && context.tvid) found.add(context.tvid);
          value.forEach(function (item) { scan(item, context, depth + 1); });
          return;
        }
        context = identity(value, context);
        Object.keys(value).forEach(function (key) { scan(value[key], context, depth + 1); });
      }
      scan(body, {tvid:"", title:"", albumId:"", prefix:""}, 0);
      return Array.from(found);
    }
    function rewrite(body) {
      try { registerEpisodeLists(decode(body)); } catch (_) {}
      var changes = 0;
      function visit(value, context, depth) {
        if (depth > 32) return value;
        var parsed = decode(value);
        if (parsed !== value) {
          var before = changes;
          var result = visit(parsed, context, depth + 1);
          return changes > before ? JSON.stringify(result) : value;
        }
        if (!value || typeof value !== "object") return value;
        if (Array.isArray(value)) {
          if (isTrackArray(value)) {
            var items = value.map(function (item) { return visit(item, context, depth + 1); });
            changes++;
            return prepareTracks(items, context);
          }
          return value.map(function (item) { return visit(item, context, depth + 1); });
        }
        context = identity(value, context);
        var before = changes, output = {};
        Object.keys(value).forEach(function (key) { output[key] = visit(value[key], context, depth + 1); });
        if (changes > before) {
          ["dstl", "prefix"].forEach(function (key) {
            if (typeof output[key] === "string") output[key] = "";
          });
        }
        return output;
      }
      var result = visit(body, {tvid: "", title: "", albumId: "", prefix: ""}, 0);
      return changes ? result : body;
    }
    function captureSource(url, raw) {
      var info = sourceByUrl.get(url);
      if (!info || captured.has(url) || typeof raw !== "string" || !raw) return Promise.resolve();
      if (capturing.has(url)) return capturing.get(url);
      var job = Promise.resolve(info.ready || registrations.get(info.tvid)).then(function (ok) {
        if (!ok) throw new Error("Episode registration failed");
        return post("/api/capture", {tvid:info.tvid,format:info.format,raw:raw});
      }).then(function () { captured.add(url); }).finally(function () { capturing.delete(url); });
      capturing.set(url, job);
      return job;
    }
    function requestUrl(input) { return typeof input === "string" ? input : input && input.url || ""; }
    function registerEpisodeLists(value) {
      var rows = new Map();
      function scan(node, parent, depth) {
        if (!node || typeof node !== "object" || depth > 30) return;
        if (Array.isArray(node)) { node.forEach(function (child) { scan(child,parent,depth+1); }); return; }
        var albumId = String(node.albumId || node.album_id || parent.albumId || "");
        var prefix = String(node.prefix || node.dstl || parent.prefix || "");
        var title = [node.entityTitle,node.display_name_v2,node.display_name,node.tvName,node.tv_name,node.title,node.name]
          .find(function (item) { return typeof item === "string" && item; }) || parent.title || "";
        var id = String(node.tvId || node.tvid || node.tv_id || node.entityId || node.entity_id || "");
        var orderMatch = String(title).match(/第\s*(\d+)\s*集|(?:episode|ep)\s*(\d+)/i);
        var order = orderMatch ? Number(orderMatch[1] || orderMatch[2]) : Number(node.orderRseat || node.order || 0);
        if (albumId && id && order > 0 && title) {
          var tracks = [];
          function findTracks(item, base, level) {
            if (!item || typeof item !== "object" || level > 12) return;
            if (Array.isArray(item)) { item.forEach(function (child) { findTracks(child,base,level+1); }); return; }
            if (item.lid != null) {
              var key = trackUrl(item);
              if (key) tracks.push({lid:String(item.lid),name:String(item.name || item.title || ""),
                url:absolute(item[key],base),format:key});
            }
            Object.keys(item).forEach(function (key) { findTracks(item[key],base,level+1); });
          }
          findTracks(node,prefix,0);
          var previous = rows.get(id);
          rows.set(id,{tvid:id,title:String(title),albumId:albumId,order:order,
            tracks:tracks.length ? tracks : (previous && previous.tracks || [])});
        }
        var next = {albumId:albumId,prefix:prefix,title:title};
        Object.keys(node).forEach(function (key) { scan(node[key],next,depth+1); });
      }
      scan(value,{albumId:"",prefix:"",title:""},0);
      if (!rows.size) return;
      var episodes = Array.from(rows.values());
      var jobs=[];
      var groups = new Map();
      episodes.forEach(function (episode) {
        if (!groups.has(episode.albumId)) groups.set(episode.albumId, []);
        groups.get(episode.albumId).push(episode);
      });
      groups.forEach(function (group, albumId) {
        var data = {albumId:albumId,title:group[0].title.replace(/\s*第\s*\d+\s*集.*$/,""),episodes:group};
        var ready = postOnce(JSON.stringify(data), "/api/album/register", data, listPosted);
        group.forEach(function (episode) {
          var track = episode.tracks.find(function (item) { return item.lid === "1"; }) ||
            episode.tracks.find(function (item) { return item.lid !== String(VI_LID); });
          if (!track) return;
          sourceByUrl.set(track.url,{tvid:episode.tvid,format:track.format,ready:ready});
          if (!queued.has(track.url)) { queued.add(track.url); jobs.push(track); }
        });
      });
      function worker(){var track=jobs.shift();if(!track)return Promise.resolve();return root.fetch(track.url)
        .then(function(response){return response.ok?response.text():Promise.reject(new Error("track unavailable"));})
        .then(function(text){return captureSource(track.url,text);}).catch(function(){queued.delete(track.url);})
        .then(worker);}
      Promise.all([worker(),worker()]);
    }
    if (typeof module !== "undefined" && module.exports) module.exports = {rewrite: rewrite};
    if (root && root.setInterval && !root.__iqiyiSessionSync &&
        (!root.location.hostname || root.location.hostname === "localwebapp.iqiyi.com")) {
      root.__iqiyiSessionSync = true;
      syncPlayerSession();
      if (root.setInterval) root.setInterval(syncPlayerSession, 5000);
    }
    if (!root) return;
    var nativePlayer = /(^|\/)player(?:_mac)?\.html$/i.test(root.location.pathname);
    var iqPlayer = /(^|\.)iq\.com$/i.test(root.location.hostname) && /\/play\//i.test(root.location.pathname);
    if (!nativePlayer && !iqPlayer) return;
    installSubtitleStyle();
    if (root.__iqiyiSubtitleEngine) return;
    installSubtitleMenuGuard();
    root.__iqiyiSubtitleEngine = {version: 6, rewrite: rewrite, titles: titles};
    if (root.fetch) {
      root.fetch = function (input, init) {
        if (requestUrl(input).indexOf(SIDE + "/") === 0) return nativeFetch(input, init);
        return nativeFetch(input, init).then(function (response) {
          var sourceUrl = requestUrl(input) || response.url;
          if (sourceByUrl.has(sourceUrl)) {
            response.clone().text().then(function (text) { return captureSource(sourceUrl, text); }).catch(function(){});
            return response;
          }
          var type = response.headers.get("content-type") || "";
          if (/video|audio|image|octet-stream|mpegurl|xml/.test(type)) return response;
          return response.clone().text().then(function (text) {
            var ids = trackTvids(text);
            return Promise.all(ids.map(function (id) { return getTranslationState(id); })).then(function () {
              var body = rewrite(text);
              if (body === text) return response;
              var headers = new Headers(response.headers);
              headers.delete("content-length"); headers.delete("content-encoding");
              return new Response(body, {status: response.status, statusText: response.statusText, headers: headers});
            });
          }).catch(function () { return response; });
        });
      };
    }
    if (root.XMLHttpRequest) {
      var proto = root.XMLHttpRequest.prototype;
      var cache = new WeakMap();
      if (proto.open && proto.send && proto.addEventListener) {
        var nativeOpen = proto.open, nativeSend = proto.send;
        proto.open = function () {
          this.__iqiyiSubtitleSourceUrl = requestUrl(arguments[1]);
          return nativeOpen.apply(this, arguments);
        };
        proto.send = function () {
          var xhr = this;
          xhr.addEventListener("loadend", function () {
            var url = xhr.__iqiyiSubtitleSourceUrl;
            if (!sourceByUrl.has(url)) return;
            try {
              var value = xhr.responseText;
              if (typeof value !== "string" && value && root.XMLSerializer) value = new root.XMLSerializer().serializeToString(value);
              captureSource(url, value).catch(function(){});
            } catch (_) {}
          }, {once:true});
          return nativeSend.apply(xhr, arguments);
        };
      }
      ["responseText", "response"].forEach(function (key) {
        var descriptor = Object.getOwnPropertyDescriptor(proto, key);
        if (!descriptor || !descriptor.get || !descriptor.configurable) return;
        Object.defineProperty(proto, key, {
          configurable: true, enumerable: descriptor.enumerable,
          get: function () {
            var raw = descriptor.get.call(this);
            if (this.readyState !== 4 || (this.responseType && this.responseType !== "text" && this.responseType !== "json")) return raw;
            var sourceUrl = this.__iqiyiSubtitleSourceUrl;
            if (sourceByUrl.has(sourceUrl)) captureSource(sourceUrl, typeof raw === "string" ? raw : JSON.stringify(raw)).catch(function(){});
            var entry = cache.get(this);
            if (!entry || entry.raw !== raw) {
              entry = {raw: raw, value: rewrite(raw)};
              cache.set(this, entry);
            }
            return entry.value;
          }
        });
      });
    }
  }

  function youkuSubtitleHook() {
    if (!root) return;
    var LAYOUT_STYLE_ID = "youku-vi-layout";
    var LAYOUT_CSS =
      '#ykPlayer [com="watermark"]{display:none!important;}' +
      ".leftnav_nav_mark{display:flex!important;align-items:center!important;height:48px!important;max-height:48px!important;overflow:hidden!important}" +
      ".leftnav_nav_mark>span{display:block!important;max-width:100%!important;white-space:nowrap!important;overflow:hidden!important;text-overflow:ellipsis!important}" +
      "[class*=pack_mark_],[class*=pack_mark_]>span{white-space:nowrap!important;overflow:hidden!important;text-overflow:ellipsis!important}" +
      ".kui-subtitle-subtitle-container,.kui-subtitle-subtitle-container *{" +
      "font-family:Arial,Helvetica,sans-serif!important;font-weight:700!important;color:#fff!important;" +
      "-webkit-text-stroke:1.2px #111!important;paint-order:stroke fill;" +
      "text-shadow:0 1px 1px #111,1px 0 1px #111,-1px 0 1px #111,0 -1px 1px #111,0 2px 4px #000!important;}";
    function installLayout() {
      var doc = root.document;
      var parent = doc && (doc.head || doc.documentElement || doc.body);
      if (!parent || !doc.createElement) return;
      var style = (doc.getElementById && doc.getElementById(LAYOUT_STYLE_ID)) || doc.createElement("style");
      style.id = LAYOUT_STYLE_ID;
      if (style.textContent !== LAYOUT_CSS) style.textContent = LAYOUT_CSS;
      if (!style.isConnected) parent.appendChild(style);
    }
    installLayout();
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
      installLayout();
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
  }

  // Native Youku pages expose location as a global, iQIYI test/wrapper pages through window.
  var place = root && root.location || (typeof location !== "undefined" ? location : null);
  var host = String(place && place.hostname || ""), href = String(place && place.href || "");
  var isYouku = /(^|\.)youku\.com$/i.test(host) ||
    /^(?:https?|client):\/\/[^\/?#]*youku\.com(?:[:\/?#]|$)/i.test(href);
  (isYouku ? youkuSubtitleHook : iqiyiSubtitleHook)();
})(typeof window === "undefined" ? null : window);
