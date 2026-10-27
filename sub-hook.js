/* Capture original tracks; expose completed AI and official iq.com subtitles in iQIYI. */
(function (root) {
  "use strict";

  function iqiyiSubtitleHook() {
    var HOOK_VERSION = 33;
    var SIDE = "http://127.0.0.1:18766";
    var nativeFetch = root && root.fetch ? root.fetch.bind(root) : null;
    function localFetch(input, options) {
      return (root.__iqiyiViLocalFetch || nativeFetch)(input, options);
    }
    function localSubtitleFetch(input, options) {
      var signal = options && options.signal;
      function retry(response, error, attempt) {
        if (signal && signal.aborted) throw signal.reason;
        if (attempt >= 4) {
          if (error) throw error;
          return response;
        }
        return new Promise(function (resolve, reject) {
          function abort() {
            clearTimeout(timer);
            signal.removeEventListener("abort", abort);
            reject(signal.reason);
          }
          var timer = setTimeout(function () {
            if (signal) signal.removeEventListener("abort", abort);
            resolve();
          }, 500 * Math.pow(2, attempt));
          if (signal) signal.addEventListener("abort", abort, {once:true});
        }).then(function () { return load(attempt + 1); });
      }
      function load(attempt) {
        if (signal && signal.aborted) return Promise.reject(signal.reason);
        return localFetch(input, options).then(function (response) {
          // The official track can still be warming up when the SDK first selects it.
          return response.status === 404 ? retry(response, null, attempt) : response;
        }, function (error) { return retry(null, error, attempt); });
      }
      return load(0);
    }
    var TOKEN = root && root.__iqiyiViToken || "";
    var tokenPromise = null;
    var tokenRetryAt = 0;
    function ensureToken() {
      if (TOKEN) return Promise.resolve(TOKEN);
      if (!nativeFetch || Date.now() < tokenRetryAt) return Promise.resolve("");
      if (tokenPromise) return tokenPromise;
      tokenPromise = localFetch(SIDE + "/api/extension-token", {cache:"no-store", credentials:"omit"})
        .then(function (response) { if (!response.ok) throw new Error("Subtitle manager unavailable"); return response.json(); })
        .then(function (config) { TOKEN = String(config.token || ""); return TOKEN; })
        .catch(function () { return ""; })
        .then(function (token) {
          tokenPromise = null;
          if (!token) tokenRetryAt = Date.now() + 2000;
          return token;
        });
      return tokenPromise;
    }
    ensureToken();
    var TRACK = /^(xml|srt|webvtt|vtt)$/;
    var OFFICIAL_LID = 90023;
    var OFFICIAL_NAME = "Tiếng Việt iq.com";
    var AI_LID = 90024;
    var AI_NAME = "Tiếng Việt AI";
    var titles = new Map();
    var albumIds = new Map();
    var registered = new Set();
    var sourceByUrl = new Map();
    var captured = new Set();
    var capturing = new Map();
    var queued = new Set();
    var sourceQueue = [];
    var sourceActive = 0;
    var listPosted = new Set();
    var posting = new Map();
    var registrations = new Map();
    var officialStates = new Map();
    var preloadedOfficialTvid = "";
    var activeOfficialTvid = "";
    var activeOfficialAvailable = false;
    var activeAiAvailable = false;
    var hiddenOptionState = new WeakMap();
    var menuObserver = null;
    var menuScanTimer = null;
    function syncPlayerSession() {
      if (!root || syncPlayerSession.pending) return;
      var account = root.QySdk && root.QySdk.Account;
      var nativeAccount = account && typeof account.getLoginInfo === "function";
      var web = /(^|\.)iqiyi\.com$/i.test(root.location.hostname) &&
        root.location.hostname !== "localwebapp.iqiyi.com";
      if (!nativeAccount && (!web || !root.document || (root.top && root.top !== root))) return;
      syncPlayerSession.pending = true;
      var result;
      try {
        if (nativeAccount) result = account.getLoginInfo();
        else {
          var cookies = {};
          String(root.document.cookie || "").split(";").forEach(function (part) {
            var pair = part.trim().split("="), name = pair.shift();
            try { cookies[name] = decodeURIComponent(pair.join("=")); } catch (_) {}
          });
          var user = {};
          try { user = JSON.parse(cookies.P00002 || "{}"); } catch (_) {}
          var uid = cookies.P00003 || user && user.uid || "";
          var auth = cookies.P00001 || "";
          // An incomplete cookie pair cannot supply an authenticated subtitle request.
          result = {authcookie: /^\d{1,24}$/.test(String(uid)) ? auth : "", uid: uid,
            deviceId: cookies.QC005 || "", dfp: (cookies.__dfp || "").split("@")[0]};
        }
      } catch (_) { syncPlayerSession.pending = false; return; }
      Promise.resolve(result && result.cache || result).then(function (info) {
        if (!info || typeof info !== "object" || !Object.keys(info).length) return;
        var appService = root.QySdk && root.QySdk.AppService;
        var system = appService && appService.getSystemInfo ? appService.getSystemInfo() : null;
        system = system && system.cache || {};
        var auth = String(info.authcookie || ""), uid = String(info.uid || "");
        var types = info.vip_types || info.vipTypes || [];
        if (typeof types === "string") types = types.split(",");
        var session = {source: nativeAccount ? "app" : "web", authcookie: auth, uid: uid,
          vipTypes: Array.isArray(types) ? types.map(String) : [],
          deviceId: String(system.deviceId || system.clientid || info.deviceId || ""),
          dfp: String(system.dfp || info.dfp || "")};
        var signature = JSON.stringify(session), now = Date.now();
        if (signature === syncPlayerSession.signature && now - syncPlayerSession.sent < 30000) return;
        return post("/api/session", session).then(function () {
          syncPlayerSession.signature = signature;
          syncPlayerSession.sent = now;
        });
      }).catch(function () {}).then(function () { syncPlayerSession.pending = false; });
    }

    function post(route, data) {
      if (!nativeFetch) return Promise.reject(new Error("Subtitle manager is unavailable"));
      return ensureToken().then(function (token) {
        if (!token) throw new Error("Subtitle manager token is unavailable");
        return localFetch(SIDE + route, {method:"POST",
          headers:{"Content-Type":"application/json", "X-Iqiyi-Token":token}, body:JSON.stringify(data)});
      }).then(function (response) {
        if (!response.ok) throw new Error("Subtitle manager HTTP " + response.status);
      });
    }
    function getOfficialSubtitleState(tvid) {
      if (!nativeFetch || !tvid) return Promise.resolve({officialAvailable:false,officialLoading:false,officialError:""});
      var cached = officialStates.get(tvid);
      if (cached && cached.value && cached.expires > Date.now()) return Promise.resolve(cached.value);
      if (cached && cached.promise) return cached.promise;
      var url = SIDE + "/api/official-subtitle-state?tvid=" + encodeURIComponent(tvid);
      var job = ensureToken().then(function (token) {
        if (!token) throw new Error("Subtitle manager token is unavailable");
        return localFetch(url, {headers:{"X-Iqiyi-Token":token}});
      }).then(function (response) {
        if (!response.ok) throw new Error("Official subtitle status unavailable");
        return response.json();
      }).then(function (state) {
        var value = {officialAvailable:state.officialAvailable === true,
          officialLoading:state.officialLoading === true, officialError:String(state.officialError || ""),
          aiAvailable:state.aiAvailable === true, aiVersion:String(state.aiVersion || "")};
        officialStates.set(tvid, {value:value, expires:Date.now() + 1000});
        return value;
      }).catch(function () {
        var value = {officialAvailable:false,officialLoading:false,officialError:""};
        officialStates.set(tvid, {value:value, expires:Date.now() + 2000});
        return value;
      });
      officialStates.set(tvid, {promise:job,expires:0});
      return job;
    }
    function isOfficialLabel(value) {
      return String(value || "").replace(/\s+/g, " ").trim() === OFFICIAL_NAME;
    }
    var officialNativeControl = null;
    var officialRuntimeRequire = null;
    function installOfficialSubtitleName() {
      // The PC player keeps its SDK and subtitle controller inside Webpack, not window.QySdk.
      var chunks = root && root.webpackChunk_iqiyi_webapp;
      if (!officialRuntimeRequire && chunks && chunks.push !== Array.prototype.push) {
        chunks.push([["iqiyiViOfficialSubtitle" + HOOK_VERSION], {}, function (require) { officialRuntimeRequire = require; }]);
      }
      if (!officialNativeControl && officialRuntimeRequire && officialRuntimeRequire.m) {
        Object.keys(officialRuntimeRequire.m).some(function (id) {
          var code = String(officialRuntimeRequire.m[id]);
          if (code.indexOf("_getSubTitleList") < 0 || code.indexOf("getAllParams") < 0) return false;
          try {
            var exports = officialRuntimeRequire(id);
            return Object.keys(exports).some(function (key) {
              var value = exports[key];
              if (!value || typeof value._getSubTitleList !== "function" || typeof value.openSubTitle !== "function") return false;
              officialNativeControl = value;
              var originalList = value._getSubTitleList;
              value._getSubTitleList = function () {
                var tracks = originalList.apply(this, arguments);
                return Array.isArray(tracks) ? tracks.map(function (track) {
                  if (Number(track.lid) === OFFICIAL_LID) return Object.assign({}, track, {name:OFFICIAL_NAME});
                  if (Number(track.lid) === AI_LID) return Object.assign({}, track, {name:AI_NAME});
                  return track;
                }) : tracks;
              };
              return true;
            });
          } catch (_) { return false; }
        });
      }
      installOfficialSubtitleLayout();
    }
    function officialRegionText(data, pts, region) {
      if (!Array.isArray(data)) return "";
      return Array.from(new Set(data.filter(function (cue) {
        return (region == null || cue.iqcomRegion === region) && Number(cue.st) <= pts && Number(cue.et) > pts;
      }).map(function (cue) { return String(cue.viText || cue.iqcomText || cue.sub || "").trim(); }).filter(Boolean))).join("\n");
    }
    function equalizeSubtitleSize(view) {
      var main = view.captionInstances && view.captionInstances.get(1);
      var sub = view.captionInstances && view.captionInstances.get(2);
      if (!main || !sub || sub.__iqiyiEqualSubtitleSize ||
          typeof main.getDualCaptionFontSize !== "function" ||
          typeof sub.getDualCaptionFontSize !== "function" || typeof sub.updateCaptionStyle !== "function") return;
      var original = sub.getDualCaptionFontSize;
      sub.getDualCaptionFontSize = function (height) {
        var primary = view.captionInstances.get(1);
        return primary ? primary.getDualCaptionFontSize(height) : original.call(this, height);
      };
      sub.__iqiyiEqualSubtitleSize = true;
      sub.updateCaptionStyle(sub.isDualCaption);
    }
    function installOfficialSubtitleLayout() {
      var sdk = officialNativeControl && officialNativeControl.subtitleSdk && officialNativeControl.subtitleSdk.sdk;
      var view = sdk && sdk.view;
      if (!view || view.__iqiyiOfficialLayoutVersion >= HOOK_VERSION || typeof view.getCurrentData !== "function" ||
          typeof view.updateCaptions !== "function") return;
      view.__iqiyiOfficialLayout = true;
      view.__iqiyiOfficialLayoutVersion = HOOK_VERSION;
      var getCurrent = view.getCurrentData;
      view.getCurrentData = function (data, pts) {
        if (!Array.isArray(data) || !data.length || (!data[0].iqcomRegion && !data[0].viText)) return getCurrent.apply(this, arguments);
        if (data[0].viText && !activeAiAvailable) return undefined;
        var text = officialRegionText(data, pts, data[0].iqcomRegion ? "bottom" : null);
        return text ? {sub:text} : undefined;
      };
      var update = view.updateCaptions;
      view.updateCaptions = function () {
        equalizeSubtitleSize(this);
        var result = update.apply(this, arguments);
        var selected = this.captionLids && Number(this.captionLids.get(1)) === OFFICIAL_LID;
        var data = selected && this.model && this.model.data[1] && this.model.data[1][OFFICIAL_LID];
        var text = selected ? officialRegionText(data, this.currentPts, "top") : "";
        var stage = this.$stage && this.$stage[0];
        var upper = this.__iqiyiOfficialUpper;
        if (text && stage && !upper) {
          upper = root.document.createElement("div");
          upper.className = "iqiyi-official-upper";
          stage.appendChild(upper);
          this.__iqiyiOfficialUpper = upper;
        }
        if (upper) {
          if (upper.textContent !== text) upper.textContent = text;
          var display = text ? "block" : "none";
          if (upper.style.display !== display) upper.style.display = display;
          var main = this.captionInstances && this.captionInstances.get(1);
          if (main && main.fontSize > 0) {
            var fontSize = Math.max(14, main.fontSize * 0.8) + "px";
            if (upper.style.fontSize !== fontSize) upper.style.fontSize = fontSize;
          }
        }
        return result;
      };
    }
    function subtitleOptionElement(labelNode) {
      var option = labelNode;
      var label = String(labelNode.textContent || "").replace(/\s+/g, " ").trim();
      for (var depth = 0; depth < 5 && option && option !== root.document.body; depth++) {
        if (String(option.textContent || "").replace(/\s+/g, " ").trim() !== label) return null;
        var role = option.getAttribute("role") || "";
        var className = typeof option.className === "string" ? option.className : "";
        // Settings buttons can contain the selected language or the whole popup.
        // Only the actual SDK option row (or an explicit ARIA menu option) is safe to change.
        if (/^(option|menuitem|menuitemradio)$/i.test(role) ||
            /(?:^|\s)simpleOptLayer_item__\S+(?:\s|$)/.test(className)) return option;
        option = option.parentElement;
      }
      return null;
    }
    function applyHiddenOption(option, hidden) {
      if (!option) return;
      if (hidden) {
        if (!hiddenOptionState.has(option)) {
          hiddenOptionState.set(option, {display:option.style.getPropertyValue("display"),
            priority:option.style.getPropertyPriority("display")});
        }
        option.style.setProperty("display", "none", "important");
      } else if (hiddenOptionState.has(option)) {
        var previous = hiddenOptionState.get(option);
        if (previous.display) option.style.setProperty("display", previous.display, previous.priority);
        else option.style.removeProperty("display");
        hiddenOptionState.delete(option);
      }
    }
    function scanSubtitleMenu() {
      menuScanTimer = null;
      if (!root || !root.document || !root.document.querySelectorAll) return;
      root.document.querySelectorAll("button,[role],li,[class],span,div").forEach(function (node) {
        var label = String(node.textContent || "").replace(/\s+/g, " ").trim();
        if (isOfficialLabel(label)) applyHiddenOption(subtitleOptionElement(node), !activeOfficialAvailable);
        if (label === AI_NAME) applyHiddenOption(subtitleOptionElement(node), !activeAiAvailable);
      });
    }
    function scheduleSubtitleMenuScan() {
      if (menuScanTimer !== null || !root || !root.setTimeout) return;
      menuScanTimer = root.setTimeout(scanSubtitleMenu, 80);
    }
    function currentSubtitleTvid() {
      var manager = officialNativeControl && officialNativeControl.videoDataManager;
      var data = manager && typeof manager.getCurrentData === "function" && manager.getCurrentData();
      var tvid = String(data && data.tvId || "");
      return /^\d{8,24}$/.test(tvid) ? tvid : "";
    }
    function syncNativeAiTrack(tvid) {
      var control = officialNativeControl, sdk = control && control.subtitleSdk && control.subtitleSdk.sdk;
      var store = control && control.store;
      if (!sdk || !store || typeof store.getProp !== "function" || typeof store.setProp !== "function" ||
          currentSubtitleTvid() !== String(tvid)) return;
      var rows = store.getProp("subTitleData");
      if (!Array.isArray(rows)) return;
      var url = SIDE + "/subtitle.xml?tvid=" + encodeURIComponent(tvid) + "&source=ai";
      var existing = rows.find(function (row) { return Number(row.lid) === AI_LID; });
      // A running player may have loaded its subtitle list before the hook update.
      // Update its reactive menu and SDK URL table without restarting the video.
      if (!existing || existing.xml !== url) {
        var track = Object.assign({}, existing || {}, {lid:AI_LID,main:1,
          pre:existing ? existing.pre : 0,name:AI_NAME,title:AI_NAME,xml:url});
        rows = rows.filter(function (row) { return Number(row.lid) !== AI_LID; }).concat([track]);
        store.setProp("subTitleData", rows);
      }
      var normalized = control._getSubTitleList().find(function (row) { return Number(row.lid) === AI_LID; });
      if (!normalized) return;
      [sdk.params, sdk.model && sdk.model.params, sdk.view && sdk.view.params].forEach(function (params) {
        if (!params || !Array.isArray(params.data)) return;
        var track = params.data.find(function (row) { return Number(row.lid) === AI_LID; });
        if (!track) params.data.push(Object.assign({}, normalized));
        else if (track.url !== url) track.url = url;
      });
    }
    function retryLocalSubtitle(tvid, lid, available, version) {
      var control = officialNativeControl;
      var sdk = control && control.subtitleSdk && control.subtitleSdk.sdk;
      var view = sdk && sdk.view;
      if (!view || !available || currentSubtitleTvid() !== String(tvid)) return;
      var tracks = control._getSubTitleList();
      var selected = Array.isArray(tracks) && tracks.some(function (track) {
        return Number(track.type) === 1 && Number(track.lid) === lid && track.status;
      });
      if (!selected) return;
      var loaded = view.model && view.model.data && view.model.data[1] && view.model.data[1][lid];
      if (lid === AI_LID && view.__iqiyiAiVersion !== version) {
        if (view.model && view.model.data && view.model.data[1]) delete view.model.data[1][lid];
        view.__iqiyiAiVersion = version;loaded = null;
      }
      var active = view.captionLids && Number(view.captionLids.get(1)) === lid;
      if (loaded && active) return;
      var retryKey = String(tvid) + ":" + lid;
      if (view.__iqiyiOfficialRetryTvid === retryKey && Date.now() < (view.__iqiyiOfficialRetryAt || 0)) return;
      view.__iqiyiOfficialRetryTvid = retryKey;
      view.__iqiyiOfficialRetryAt = Date.now() + 5000;
      try { control.openSubTitle(1, lid); } catch (_) {}
    }
    function applyLocalSubtitleState(tvid, state) {
      activeOfficialAvailable = state.officialAvailable;
      activeAiAvailable = state.aiAvailable === true;
      syncNativeAiTrack(tvid);
      retryLocalSubtitle(tvid, OFFICIAL_LID, activeOfficialAvailable);
      retryLocalSubtitle(tvid, AI_LID, activeAiAvailable, state.aiVersion);
      scheduleSubtitleMenuScan();
    }
    function setActiveOfficialTrack(tvid) {
      if (!tvid || !root || !root.document) return;
      var playing = currentSubtitleTvid();
      if (playing && playing !== String(tvid)) return;
      activeOfficialTvid = String(tvid);
      var cached = officialStates.get(activeOfficialTvid);
      activeOfficialAvailable = !!(cached && cached.value && cached.value.officialAvailable);
      activeAiAvailable = !!(cached && cached.value && cached.value.aiAvailable);
      scheduleSubtitleMenuScan();
      getOfficialSubtitleState(activeOfficialTvid).then(function (state) {
        if (activeOfficialTvid !== String(tvid)) return;
        applyLocalSubtitleState(tvid, state);
      });
    }
    function refreshOfficialSubtitle() {
      installOfficialSubtitleName();
      var playing = currentSubtitleTvid();
      if (!playing) return;
      if (playing !== activeOfficialTvid) { setActiveOfficialTrack(playing); return; }
      getOfficialSubtitleState(playing).then(function (state) {
        if (activeOfficialTvid !== playing) return;
        applyLocalSubtitleState(playing, state);
      });
    }
    function installOfficialSubtitleGuard() {
      var doc = root && root.document;
      if (!doc || !doc.addEventListener || doc.__iqiyiLocalSubtitleGuardVersion >= HOOK_VERSION) return;
      doc.__iqiyiOfficialSubtitleGuard = true;
      doc.__iqiyiLocalSubtitleGuardVersion = HOOK_VERSION;
      if (root.MutationObserver && doc.documentElement) {
        menuObserver = new root.MutationObserver(scheduleSubtitleMenuScan);
        menuObserver.observe(doc.documentElement, {childList:true, subtree:true});
      }
      if (root.setInterval) root.setInterval(refreshOfficialSubtitle, 1000);
    }
    function installSubtitleStyle() {
      var doc = root.document;
      if (!doc) return;
      function addStyle() {
        if (!doc.documentElement) return;
        var style = doc.getElementById("iqiyi-vi-subtitle-css") || doc.createElement("style");
        style.id = "iqiyi-vi-subtitle-css";
        style.setAttribute("data-hook-version", "28");
        style.textContent =
          'img[src*="/watermark_rightTop"],img[src*="/watermark_rightBottom"]{display:none!important;}' +
          '#pcaSubtitleContainer,#pcaSubtitleContainer *,.caption-main,.caption-main *,.caption-sub,.caption-sub *,.iqiyi-official-upper{' +
          'font-family:Arial,Helvetica,sans-serif!important;font-weight:700!important;color:#fff!important;' +
          // Stroke rasterization leaves an inner fringe in the player WebView; use a flat outline.
          '-webkit-text-stroke:0!important;' +
          'text-shadow:-2px -2px 0 #111,0 -2px 0 #111,2px -2px 0 #111,2px 0 0 #111,2px 2px 0 #111,0 2px 0 #111,-2px 2px 0 #111,-2px 0 0 #111!important;}' +
          '.caption-main::after,.caption-sub::after{content:none!important;}' +
          '.iqiyi-official-upper{position:absolute;top:6%;left:5%;width:90%;box-sizing:border-box;' +
          'white-space:pre-line;text-align:center;line-height:1.4;pointer-events:none;z-index:2;' +
          'font-size:clamp(14px,3.8vh,32px);}' +
          'video::cue{font-family:Arial,Helvetica,sans-serif;font-weight:700;color:#fff;background:transparent;' +
          '-webkit-text-stroke:0;text-shadow:-2px -2px 0 #111,0 -2px 0 #111,2px -2px 0 #111,2px 0 0 #111,2px 2px 0 #111,0 2px 0 #111,-2px 2px 0 #111,-2px 0 0 #111;}';
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
    function numberedSeriesTitle(value) {
      var match = String(value || "").match(/^(.+?)\s*第\s*\d+\s*集|^(.+?)\s+(?:episode|ep)\s*\d+/i);
      return match ? (match[1] || match[2]).trim() : "";
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
      if (!/^https?:\/\//i.test(url)) {
        var proto = (prefix.match(/^https?:/i) || ["https:"])[0];
        if (url.indexOf("//") === 0) url = proto + url;
        else {
          var origin = (prefix.match(/^https?:\/\/[^/]+/i) || ["https://meta.video.iqiyi.com"])[0];
          url = url.charAt(0) === "/" ? origin + url : prefix.replace(/\/?$/, "/") + url.replace(/^\//, "");
        }
      }
      // iQIYI still returns HTTP subtitle URLs; HTTPS players cannot request them.
      return url.replace(/^http:\/\/(?:[a-z0-9-]+\.)*iqiyi\.com(?=[:/?#]|$)/i, function (host) {
        return host.replace(/^http:/i, "https:");
      });
    }
    function isTrackArray(items) {
      return items.some(function (item) {
        return item && typeof item === "object" && !Array.isArray(item) &&
          item.lid != null && !!trackUrl(item);
      });
    }
    function prepareTracks(items, context) {
      installOfficialSubtitleName();
      var chinese = items.find(function (item) { return item && String(item.lid) === "1"; });
      var preferred = chinese || items.find(function (item) { return item && trackUrl(item); });
      var sourceTracks = items.filter(function (item) { return item && trackUrl(item) &&
        !(typeof item.xml === "string" && item.xml.indexOf(SIDE + "/subtitle.xml?") === 0); }).map(function (item) {
        var key = trackUrl(item), url = absolute(item[key], context.prefix);
        if (item === preferred) sourceByUrl.set(url, {tvid:context.tvid,format:key});
        return {lid:String(item.lid || ""),name:String(item.name || item.title || ""),url:url,format:key};
      });
      if (context.tvid) {
        var registration = {tvid:context.tvid,title:context.title,albumId:context.albumId,tracks:sourceTracks};
        registrations.set(context.tvid, postOnce(JSON.stringify(registration), "/api/register", registration, registered));
      }
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
      if (!output.some(function (item) { return item && Number(item.lid) === OFFICIAL_LID; })) {
        output.push({lid:OFFICIAL_LID,main:1,pre:0,name:OFFICIAL_NAME,title:OFFICIAL_NAME,
          xml:SIDE + "/subtitle.xml?tvid=" + encodeURIComponent(context.tvid) + "&source=iqcom"});
      }
      if (!output.some(function (item) { return item && Number(item.lid) === AI_LID; })) {
        output.push({lid:AI_LID,main:1,pre:0,name:AI_NAME,title:AI_NAME,
          xml:SIDE + "/subtitle.xml?tvid=" + encodeURIComponent(context.tvid) + "&source=ai"});
      }
      setActiveOfficialTrack(context.tvid);
      return output;
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
        Object.keys(value).forEach(function (key) {
          // A film without domestic subtitle tracks can still have an iq.com track.
          if (key === "stl" && Array.isArray(value[key]) && !value[key].length && context.tvid) {
            changes++;
            output[key] = prepareTracks([], context);
          } else if (key === "program" && context.tvid && value[key] &&
                     !Array.isArray(value[key]) && Array.isArray(value[key].video) && value[key].stl == null) {
            output[key] = visit(value[key], context, depth + 1);
            output[key].stl = prepareTracks([], context);
            changes++;
          } else output[key] = visit(value[key], context, depth + 1);
        });
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
    function pumpSourceQueue() {
      while (sourceActive < 2 && sourceQueue.length) {
        (function (track) {
          sourceActive++;
          var controller = typeof AbortController === "function" ? new AbortController() : null;
          var timer = controller ? setTimeout(function () { controller.abort(); }, 20000) : null;
          Promise.resolve().then(function () {
            return nativeFetch(track.url, controller ? {signal:controller.signal} : undefined);
          }).then(function (response) {
            if (!response.ok) throw new Error("track unavailable");
            return response.text();
          }).finally(function () { if (timer) clearTimeout(timer); })
            .then(function (text) { return captureSource(track.url, text); })
            .catch(function () { queued.delete(track.url); })
            .finally(function () { sourceActive--; pumpSourceQueue(); });
        })(sourceQueue.shift());
      }
    }
    function requestUrl(input) { return typeof input === "string" ? input : input && input.url || ""; }
    function registerEpisodeLists(value) {
      var rows = new Map();
      function scan(node, parent, depth) {
        if (!node || typeof node !== "object" || depth > 30) return;
        if (Array.isArray(node)) { node.forEach(function (child) { scan(child,parent,depth+1); }); return; }
        var albumId = String(node.albumId || node.album_id || parent.albumId || "");
        var prefix = String(node.prefix || node.dstl || parent.prefix || "");
        var candidates = [node.entityTitle,node.display_name_v2,node.display_name,node.tvName,node.tv_name,node.title,node.name]
          .filter(function (item) { return typeof item === "string" && item; });
        var title = candidates.find(numberedSeriesTitle) || candidates[0] || parent.title || "";
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
      var groups = new Map();
      episodes.forEach(function (episode) {
        if (!groups.has(episode.albumId)) groups.set(episode.albumId, []);
        groups.get(episode.albumId).push(episode);
      });
      groups.forEach(function (group, albumId) {
        var data = {albumId:albumId,title:numberedSeriesTitle(group[0].title),episodes:group};
        var ready = postOnce(JSON.stringify(data), "/api/album/register", data, listPosted);
        group.forEach(function (episode) {
          var track = episode.tracks.find(function (item) { return item.lid === "1"; }) ||
            episode.tracks.find(function (item) { return item.lid !== "90023"; });
          if (!track) return;
          sourceByUrl.set(track.url,{tvid:episode.tvid,format:track.format,ready:ready});
          if (!queued.has(track.url)) { queued.add(track.url); sourceQueue.push(track); }
        });
      });
      pumpSourceQueue();
    }
    if (typeof module !== "undefined" && module.exports) module.exports = {rewrite: rewrite};
    if (root && root.setInterval && !root.__iqiyiSessionSync) {
      root.__iqiyiSessionSync = true;
      syncPlayerSession();
      if (root.setInterval) root.setInterval(syncPlayerSession, 5000);
    }
    if (!root) return;
    var nativePlayer = /(^|\/)player(?:_mac)?\.html$/i.test(root.location.pathname);
    var iqPlayer = /(^|\.)iqiyi\.com$/i.test(root.location.hostname) && /(?:\/play\/|\/v_[^/]+\.html?$)/i.test(root.location.pathname);
    if (!nativePlayer && !iqPlayer) return;
    // Web pages can expose the active video before any intercepted subtitle request.
    function syncWebEpisode() {
      if (!iqPlayer) return;
      var page = root.Q && root.Q.PageInfo;
      var stage = root.playbackPageStageStatus;
      var accelerated = stage && stage._accData || root.QiyiPlayerProphetData;
      var info = accelerated && accelerated.videoInfo || page && page.playPageInfo;
      if (!info || typeof info !== "object") return;
      var tvid = String(info.tvId || info.tvid || "");
      var albumId = String(info.albumId || info.album_id || "");
      if (!/^\d{1,20}$/.test(tvid) || !/^\d{1,24}$/.test(albumId)) return;
      if (preloadedOfficialTvid !== tvid) {
        preloadedOfficialTvid = tvid;
        getOfficialSubtitleState(tvid).catch(function () {});
      }
      var album = info.album || {};
      var title = String(info.tvName || info.entityTitle || info.name || info.title || album.albumName || album.name || "");
      var order = title.match(/第\s*(\d+)\s*集/);
      var data = {tvid:tvid, albumId:albumId, title:title,
        order:Number(info.order || (order && order[1]) || 0), tracks:[]};
      var albumTitle = String(info.albumName || album.albumName || album.name || numberedSeriesTitle(title));
      if (albumTitle) data.albumTitle = albumTitle;
      postOnce(JSON.stringify(data), "/api/register", data, registered);
    }
    installSubtitleStyle();
    if (root.__iqiyiSubtitleEngine && root.__iqiyiSubtitleEngine.version >= HOOK_VERSION) return;
    syncWebEpisode();
    if (iqPlayer && root.setInterval) root.setInterval(syncWebEpisode, 3000);
    installOfficialSubtitleGuard();
    root.__iqiyiSubtitleEngine = {version: HOOK_VERSION, rewrite: rewrite, titles: titles};

    // The accelerator assigns encoded DASH metadata directly, bypassing fetch/XHR/JSONP.
    function rewriteAccelerator(value) {
      if (!value || typeof value !== "object" || typeof value.ev !== "string") return value;
      try {
        var plain = value.ev.split("").map(function (ch) { return String.fromCharCode(ch.charCodeAt(0) ^ 90); }).join("");
        var parsed = JSON.parse(plain);
        var next = rewrite(parsed);
        if (next === parsed) return value;
        var encoded = JSON.stringify(next).split("").map(function (ch) { return String.fromCharCode(ch.charCodeAt(0) ^ 90); }).join("");
        return Object.assign({}, value, {ev:encoded});
      } catch (_) { return value; }
    }
    if (iqPlayer) {
      var bootstrapDescriptor = Object.getOwnPropertyDescriptor(root, "QiyiPlayerProphetData");
      if (!bootstrapDescriptor || (bootstrapDescriptor.configurable && !bootstrapDescriptor.get && !bootstrapDescriptor.set && bootstrapDescriptor.writable)) {
        var bootstrapValue = rewriteAccelerator(root.QiyiPlayerProphetData);
        Object.defineProperty(root, "QiyiPlayerProphetData", {
          configurable:true, enumerable:true,
          get:function () { return bootstrapValue; },
          set:function (value) { bootstrapValue = rewriteAccelerator(value); syncWebEpisode(); }
        });
      }
    }

    // The web player also loads DASH through JSONP. Rewrite its payload before
    // the player's callback consumes it, just as the fetch/XHR hooks do below.
    function hookJsonp(script) {
      if (!script || script.tagName !== "SCRIPT" || !script.src) return;
      var url;
      try { url = new URL(script.src, root.location.href); } catch (_) { return; }
      if (!/(^|\.)iqiyi\.com$/i.test(url.hostname)) return;
      var name = url.searchParams.get("callback") || url.searchParams.get("cb");
      if (!name || !/^[A-Za-z_$][\w$]*$/.test(name)) return;
      var callback = root[name];
      if (typeof callback !== "function" || jsonpCallbacks.has(callback)) return;
      var wrapped = function () {
        var self = this, args = Array.prototype.slice.call(arguments);
        args[0] = rewrite(args[0]);
        return callback.apply(self, args);
      };
      jsonpCallbacks.add(wrapped);
      root[name] = wrapped;
    }
    var jsonpCallbacks = new WeakSet();
    if (root.Node && root.Node.prototype) {
      ["appendChild", "insertBefore"].forEach(function (key) {
        var original = root.Node.prototype[key];
        if (!original) return;
        root.Node.prototype[key] = function (node) {
          hookJsonp(node);
          return original.apply(this, arguments);
        };
      });
    }
    if (root.fetch) {
      root.fetch = function (input, init) {
        var url = requestUrl(input);
        if (url === SIDE + "/subtitle.xml" || url.indexOf(SIDE + "/subtitle.xml?") === 0) return localSubtitleFetch(input, init);
        if (url.indexOf(SIDE + "/") === 0) return localFetch(input, init);
        return nativeFetch(input, init).then(function (response) {
          var sourceUrl = requestUrl(input) || response.url;
          if (sourceByUrl.has(sourceUrl)) {
            response.clone().text().then(function (text) { return captureSource(sourceUrl, text); }).catch(function(){});
            return response;
          }
          var type = response.headers.get("content-type") || "";
          if (/video|audio|image|octet-stream|mpegurl|xml/.test(type)) return response;
          return response.clone().text().then(function (text) {
            var body = rewrite(text);
            if (body === text) return response;
            var headers = new Headers(response.headers);
            headers.delete("content-length"); headers.delete("content-encoding");
            return new Response(body, {status: response.status, statusText: response.statusText, headers: headers});
          }).catch(function () { return response; });
        });
      };
    }
    if (root.XMLHttpRequest) {
      var proto = root.XMLHttpRequest.prototype;
      var cache = new WeakMap();
      if (proto.open && proto.send && proto.addEventListener) {
        var nativeOpen = proto.open, nativeSend = proto.send;
        var nativeSetRequestHeader = proto.setRequestHeader;
        var nativeAbort = proto.abort;
        function cancelRelay(xhr) {
          var relay = xhr.__iqiyiSubtitleRelay;
          if (!relay) return;
          xhr.__iqiyiSubtitleRelay = null;
          if (relay.timer) clearTimeout(relay.timer);
          relay.controller.abort();
        }
        proto.open = function () {
          cancelRelay(this);
          this.__iqiyiSubtitleAuthSent = false;
          this.__iqiyiSubtitleRequest = (this.__iqiyiSubtitleRequest || 0) + 1;
          this.__iqiyiSubtitleAsync = arguments[2] !== false;
          this.__iqiyiSubtitleSourceUrl = requestUrl(arguments[1]);
          return nativeOpen.apply(this, arguments);
        };
        if (nativeSetRequestHeader && !proto.__iqiyiSubtitleHeaderGuard) {
          proto.__iqiyiSubtitleHeaderGuard = true;
          proto.setRequestHeader = function (name, value) {
            var url = this.__iqiyiSubtitleSourceUrl || "";
            if (String(name).toLowerCase() === "x-iqiyi-token" &&
                (url === SIDE + "/subtitle.xml" || url.indexOf(SIDE + "/subtitle.xml?") === 0)) {
              // Legacy hooks remain underneath during a live upgrade. Repeated
              // setRequestHeader calls append values, producing an invalid token.
              if (this.__iqiyiSubtitleAuthSent) return;
              this.__iqiyiSubtitleAuthSent = true;
            }
            return nativeSetRequestHeader.apply(this, arguments);
          };
        }
        if (nativeAbort) proto.abort = function () {
          cancelRelay(this);
          this.__iqiyiSubtitleRequest = (this.__iqiyiSubtitleRequest || 0) + 1;
          return nativeAbort.apply(this, arguments);
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
          var localUrl = xhr.__iqiyiSubtitleSourceUrl;
          if (localUrl === SIDE + "/subtitle.xml" || localUrl.indexOf(SIDE + "/subtitle.xml?") === 0) {
            if (root.__iqiyiViLocalFetch && xhr.__iqiyiSubtitleAsync) {
              var generation = xhr.__iqiyiSubtitleRequest;
              var responseType = xhr.responseType, timeout = xhr.timeout;
              var relay = {controller:new AbortController(), timer:null};
              xhr.__iqiyiSubtitleRelay = relay;
              function fail(event) {
                if (generation !== xhr.__iqiyiSubtitleRequest) return;
                xhr.abort();
                xhr.dispatchEvent(new Event(event));
                xhr.dispatchEvent(new Event("loadend"));
              }
              relay.timer = timeout ? setTimeout(function () { fail("timeout"); }, timeout) : null;
              localSubtitleFetch(localUrl, {signal:relay.controller.signal}).then(function (response) {
                if (!response.ok) throw new Error("Subtitle manager HTTP " + response.status);
                return response.blob();
              }).then(function (blob) {
                if (relay.timer) clearTimeout(relay.timer);
                if (generation !== xhr.__iqiyiSubtitleRequest) return;
                xhr.__iqiyiSubtitleRelay = null;
                // Keep the player's native XHR/XML parsing, using bytes supplied by the worker.
                var blobUrl = root.URL.createObjectURL(blob);
                xhr.addEventListener("loadend", function () { root.URL.revokeObjectURL(blobUrl); }, {once:true});
                try {
                  nativeOpen.call(xhr, "GET", blobUrl, true);
                  xhr.responseType = responseType;
                  xhr.timeout = timeout;
                  nativeSend.call(xhr);
                } catch (error) { root.URL.revokeObjectURL(blobUrl); throw error; }
              }).catch(function (error) {
                if (relay.timer) clearTimeout(relay.timer);
                if (generation !== xhr.__iqiyiSubtitleRequest) return;
                console.warn("[iQIYI Việt hóa]", error.message);
                fail("error");
              });
              return;
            }
            var args = arguments;
            var sendGeneration = xhr.__iqiyiSubtitleRequest;
            function sendLocal(token) {
              if (sendGeneration !== xhr.__iqiyiSubtitleRequest) return;
              // Native XHR may omit Origin. Authenticate only the exact loopback route;
              // a query token would leak if CaptionSDK retries through its remote relay.
              if (token) xhr.setRequestHeader("X-Iqiyi-Token", token);
              return nativeSend.apply(xhr, args);
            }
            if (TOKEN) return sendLocal(TOKEN);
            ensureToken().then(sendLocal);
            return;
          }
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
      "-webkit-text-stroke:2.2px #111!important;paint-order:stroke fill;" +
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
    var VERSION = 6;
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
    // Remove cached output from the retired live-caption translator.
    try { localStorage.removeItem("__youkuViSubtitleCacheV1"); } catch (_) {}
    var REGISTERED = {}, REGISTERING = {}, CAPTURED = {}, captureContext = null, captureBuffer = [], captureTimer = 0;
    var captureUpload = Promise.resolve();
    var currentContext = null, lastFullScan = 0, lastRegister = 0;
    var stopped = false;

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
      // Detach every batch before the player can replace the episode context.
      var context = captureContext;
      while (captureBuffer.length) enqueueCapture(context, captureBuffer.splice(0, 200));
    }
    function enqueueCapture(context, batch) {
      var payload = {tvid: context.tvid, format: "srt", raw: toSrt(batch), append: true};
      function send() {
        return ensureRegistered(context).then(function (ready) {
          if (!ready) throw new Error("manager unavailable");
          return managerPost("/api/capture", payload);
        }).catch(function () {
          if (!stopped) return new Promise(function (resolve) { setTimeout(resolve, 5000); }).then(send);
        });
      }
      captureUpload = captureUpload.then(send);
    }
    function queueCapture(context, cues) {
      if (!TOKEN || !context || !cues || !cues.length) return;
      if (captureContext && captureContext.tvid !== context.tvid) {
        flushCapture(); CAPTURED = {};
      }
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
    function tick() {
      installLayout();
      var context = pageContext();
      if (!context) {
        if (currentContext) { flushCapture(); currentContext = null; captureContext = null; CAPTURED = {}; }
        return;
      }
      if (!currentContext || context.tvid !== currentContext.tvid) {
        flushCapture();
        currentContext = context; captureContext = context; CAPTURED = {};
        captureBuffer = []; lastRegister = 0; lastFullScan = 0;
      } else currentContext = context;
      if (Date.now() - lastRegister > 12000) {
        lastRegister = Date.now(); ensureRegistered(context);
      }
      if (Date.now() - lastFullScan > 2500) {
        lastFullScan = Date.now();
        var full = fullTrackCues();
        if (full.length) queueCapture(context, full);
      }
      var cue = visibleCue();
      if (cue) queueCapture(context, [cue]);
    }
    root.__youkuViSubtitleStatus = function () {
      return {captured:Object.keys(CAPTURED).length,registered:!!(currentContext && REGISTERED[currentContext.tvid])};
    };
    root.__youkuViSubtitleRefresh = installLayout;
    var tickTimer = setInterval(tick, 250);
    root.__youkuViSubtitleStop = function () {
      stopped = true;
      clearInterval(tickTimer);
      if (captureTimer) { clearTimeout(captureTimer); captureTimer = 0; }
      flushCapture();
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
