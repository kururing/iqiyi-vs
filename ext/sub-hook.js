/* Player subtitle hooks for iQIYI and Youku in one file; the router at the bottom picks the provider.
   - iQIYI: register player-provided subtitle tracks and use translated local tracks.
   - Youku: translate live captions, capture them in the shared subtitle manager and apply Youku layout CSS. */
(function (root) {
  "use strict";

  function iqiyiSubtitleHook() {
    var SIDE = "http://127.0.0.1:18766";
    var nativeFetch = root && root.fetch ? root.fetch.bind(root) : null;
    function localFetch(input, options) {
      return (root.__iqiyiViLocalFetch || nativeFetch)(input, options);
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
    var VI_LID = 23;
    var VI_NAME = "Tiếng Việt AI";
    var OFFICIAL_LID = 90023;
    var OFFICIAL_NAME = "Tiếng Việt iq.com";
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
    var translationStates = new Map();
    var activeViTvid = "";
    var activeViDisabled = true;
    var activeAiManaged = true;
    var activeOfficialAvailable = false;
    var disabledOptionState = new WeakMap();
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
      }).then(function (response) { if (!response.ok) throw new Error("Subtitle manager HTTP " + response.status); });
    }
    function getTranslationState(tvid) {
      if (!nativeFetch || !tvid) return Promise.resolve({available:false, translating:true});
      var cached = translationStates.get(tvid);
      if (cached && cached.value && cached.expires > Date.now()) return Promise.resolve(cached.value);
      if (cached && cached.promise) return cached.promise;
      var url = SIDE + "/api/translation-state?tvid=" + encodeURIComponent(tvid);
      var job = ensureToken().then(function (token) {
        if (!token) throw new Error("Subtitle manager token is unavailable");
        return localFetch(url + "&token=" + encodeURIComponent(token));
      }).then(function (response) {
        if (!response.ok) throw new Error("Translation status unavailable");
        return response.json();
      }).then(function (state) {
        var value = {available:state.available === true, translating:state.translating === true,
          officialAvailable:state.officialAvailable === true, officialLoading:state.officialLoading === true,
          officialError:String(state.officialError || "")};
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
    function primeTranslationStates(ids) {
      if (!ids.length) return Promise.resolve();
      // Subtitle availability must not stall playback when the manager is offline.
      return new Promise(function (resolve) {
        var timer = setTimeout(resolve, 1500);
        Promise.all(ids.map(getTranslationState)).then(function () { clearTimeout(timer); resolve(); });
      });
    }
    function isViLabel(value) {
      return /^(?:tiếng\s*việt(?:\s*(?:ai|\(ai\)))?|vietnamese(?:\s*\(ai\))?|越南语|越南文)$/i.test(
        String(value || "").replace(/\s+/g, " ").trim());
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
        chunks.push([["iqiyiViOfficialSubtitle"], {}, function (require) { officialRuntimeRequire = require; }]);
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
                  if (Number(track.lid) === VI_LID && activeAiManaged) return Object.assign({}, track, {name:VI_NAME});
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
      if (!view || view.__iqiyiOfficialLayout || typeof view.getCurrentData !== "function" ||
          typeof view.updateCaptions !== "function") return;
      view.__iqiyiOfficialLayout = true;
      var getCurrent = view.getCurrentData;
      view.getCurrentData = function (data, pts) {
        if (!Array.isArray(data) || !data.length || (!data[0].iqcomRegion && !data[0].viText)) return getCurrent.apply(this, arguments);
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
    function optionForTarget(target) {
      var node = target && (target.nodeType === 1 ? target : target.parentElement);
      while (node && node !== root.document.body) {
        var label = String(node.textContent || "").replace(/\s+/g, " ").trim();
        if (node.nodeType === 1 && (isViLabel(label) || isOfficialLabel(label))) {
          var option = subtitleOptionElement(node);
          if (option) return {element:option, official:isOfficialLabel(label)};
        }
        node = node.parentElement;
      }
      return null;
    }
    function applyDisabledOption(option, disabled, message) {
      if (!option) return;
      var previous = disabledOptionState.get(option);
      if (disabled) {
        if (!previous) {
          previous = {aria:option.getAttribute("aria-disabled"), disabled:"disabled" in option ? option.disabled : null,
            opacity:option.style.opacity, cursor:option.style.cursor, title:option.getAttribute("title")};
          disabledOptionState.set(option, previous);
        }
        option.setAttribute("aria-disabled", "true");
        if (previous.disabled !== null) option.disabled = true;
        option.style.opacity = "0.45";
        option.style.cursor = "not-allowed";
        if (message) option.setAttribute("title", message);
        return;
      }
      if (!previous) return;
      if (previous.aria === null) option.removeAttribute("aria-disabled");
      else option.setAttribute("aria-disabled", previous.aria);
      if (previous.disabled !== null) option.disabled = previous.disabled;
      option.style.opacity = previous.opacity;
      option.style.cursor = previous.cursor;
      if (previous.title === null) option.removeAttribute("title");
      else option.setAttribute("title", previous.title);
      disabledOptionState.delete(option);
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
      var candidates = root.document.querySelectorAll("button,[role],li,[class],span,div");
      candidates.forEach(function (node) {
        // Reading innerText forces layout and can trigger unrelated HTTP background images.
        var label = String(node.textContent || "").replace(/\s+/g, " ").trim();
        if (isOfficialLabel(label)) applyHiddenOption(subtitleOptionElement(node), !activeOfficialAvailable);
        else if (isViLabel(label)) applyDisabledOption(subtitleOptionElement(node), activeViDisabled, "");
      });
    }
    function scheduleSubtitleMenuScan() {
      if (menuScanTimer !== null || !root || !root.setTimeout) return;
      menuScanTimer = root.setTimeout(scanSubtitleMenu, 80);
    }
    function applyActiveSubtitleState(state) {
      activeViDisabled = activeAiManaged && (!state.available || state.translating);
      activeOfficialAvailable = state.officialAvailable === true;
    }
    function currentSubtitleTvid() {
      var manager = officialNativeControl && officialNativeControl.videoDataManager;
      var data = manager && typeof manager.getCurrentData === "function" && manager.getCurrentData();
      var tvid = String(data && data.tvId || "");
      return /^\d{8,24}$/.test(tvid) ? tvid : "";
    }
    function retryOfficialSubtitle(tvid, state) {
      var control = officialNativeControl;
      var sdk = control && control.subtitleSdk && control.subtitleSdk.sdk;
      var view = sdk && sdk.view;
      if (!view || !state.officialAvailable || currentSubtitleTvid() !== String(tvid)) return;
      // The controller retains the user's choice even when the SDK never activated a failed load.
      var tracks = control._getSubTitleList();
      var selected = Array.isArray(tracks) && tracks.some(function (track) {
        return Number(track.type) === 1 && Number(track.lid) === OFFICIAL_LID && track.status;
      });
      if (!selected) return;
      var loaded = view.model && view.model.data && view.model.data[1] && view.model.data[1][OFFICIAL_LID];
      var active = view.captionLids && Number(view.captionLids.get(1)) === OFFICIAL_LID;
      if (loaded && active) return;
      if (view.__iqiyiOfficialRetryTvid === String(tvid) && Date.now() < (view.__iqiyiOfficialRetryAt || 0)) return;
      // A cold cache can fail the SDK's initial load, including a saved language choice.
      view.__iqiyiOfficialRetryTvid = String(tvid);
      view.__iqiyiOfficialRetryAt = Date.now() + 5000;
      try { control.openSubTitle(1, OFFICIAL_LID); } catch (_) {}
    }
    function setActiveViTrack(tvid, managed) {
      if (!tvid || !root || !root.document) return;
      // DASH for a prefetched episode must not hide tracks for the video being watched.
      var playing = currentSubtitleTvid();
      if (playing && playing !== String(tvid)) return;
      activeViTvid = String(tvid);
      activeAiManaged = managed !== false;
      activeViDisabled = activeAiManaged;
      var cached = translationStates.get(activeViTvid);
      activeOfficialAvailable = !!(cached && cached.value && cached.value.officialAvailable);
      scheduleSubtitleMenuScan();
      getTranslationState(activeViTvid).then(function (state) {
        if (activeViTvid !== String(tvid)) return;
        applyActiveSubtitleState(state);
        retryOfficialSubtitle(tvid, state);
        scheduleSubtitleMenuScan();
      });
    }
    function refreshActiveViTrack() {
      installOfficialSubtitleName();
      var playing = currentSubtitleTvid();
      if (playing && playing !== activeViTvid) {
        var tracks = officialNativeControl._getSubTitleList();
        var vi = Array.isArray(tracks) && tracks.find(function (track) { return Number(track.lid) === VI_LID; });
        setActiveViTrack(playing, !vi || String(vi.url || "").indexOf(SIDE + "/subtitle.xml?") === 0);
        return;
      }
      if (!activeViTvid) return;
      var tvid = activeViTvid;
      getTranslationState(tvid).then(function (state) {
        if (activeViTvid !== tvid) return;
        applyActiveSubtitleState(state);
        retryOfficialSubtitle(tvid, state);
        scheduleSubtitleMenuScan();
      });
    }
    function installSubtitleMenuGuard() {
      var doc = root && root.document;
      if (!doc || !doc.addEventListener || doc.__iqiyiViMenuGuard) return;
      doc.__iqiyiViMenuGuard = true;
      function blockUnavailableSelection(event) {
        if (!activeViTvid) return;
        if (event.type === "keydown" && event.key !== "Enter" && event.key !== " ") return;
        var option = optionForTarget(event.target);
        if (!option || option.official || !activeViDisabled) return;
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
        style.setAttribute("data-hook-version", "27");
        style.textContent =
          'img[src*="/watermark_rightTop"],img[src*="/watermark_rightBottom"]{display:none!important;}' +
          '#pcaSubtitleContainer,#pcaSubtitleContainer *,.caption-main,.caption-main *,.caption-sub,.caption-sub *,.iqiyi-official-upper{' +
          'font-family:Arial,Helvetica,sans-serif!important;font-weight:700!important;color:#fff!important;' +
          // Stroke rasterization leaves an inner fringe in the player WebView; use a flat outline.
          '-webkit-text-stroke:0!important;' +
          'text-shadow:-1px -1px 0 #111,0 -1px 0 #111,1px -1px 0 #111,1px 0 0 #111,1px 1px 0 #111,0 1px 0 #111,-1px 1px 0 #111,-1px 0 0 #111!important;}' +
          '.caption-main::after,.caption-sub::after{content:none!important;}' +
          '.iqiyi-official-upper{position:absolute;top:6%;left:5%;width:90%;box-sizing:border-box;' +
          'white-space:pre-line;text-align:center;line-height:1.4;pointer-events:none;z-index:2;' +
          'font-size:clamp(14px,3.8vh,32px);}' +
          'video::cue{font-family:Arial,Helvetica,sans-serif;font-weight:700;color:#fff;background:transparent;' +
          '-webkit-text-stroke:0;text-shadow:-1px -1px 0 #111,0 -1px 0 #111,1px -1px 0 #111,1px 0 0 #111,1px 1px 0 #111,0 1px 0 #111,-1px 1px 0 #111,-1px 0 0 #111;}';
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
        // This read-only route is origin-checked by the local manager; avoid a token race
        // when iQIYI requests the injected track before the token fetch has completed.
        xml: SIDE + "/subtitle.xml?tvid=" + encodeURIComponent(context.tvid)
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
      output.push({lid:OFFICIAL_LID, main:1, pre:0, name:OFFICIAL_NAME, title:OFFICIAL_NAME,
        xml:SIDE + "/subtitle.xml?tvid=" + encodeURIComponent(context.tvid) + "&source=iqcom"});
      if (output.some(function (item) { return item && String(item.lid) === String(VI_LID); })) {
        setActiveViTrack(context.tvid, false);
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
        if (context.tvid && value.program && !Array.isArray(value.program) &&
            Array.isArray(value.program.video) && value.program.stl == null) found.add(context.tvid);
        Object.keys(value).forEach(function (key) {
          if (key === "stl" && Array.isArray(value[key]) && !value[key].length && context.tvid) found.add(context.tvid);
          scan(value[key], context, depth + 1);
        });
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
            episode.tracks.find(function (item) { return item.lid !== String(VI_LID); });
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
    if (root.__iqiyiSubtitleEngine) return;
    syncWebEpisode();
    if (iqPlayer && root.setInterval) root.setInterval(syncWebEpisode, 3000);
    installSubtitleMenuGuard();
    root.__iqiyiSubtitleEngine = {version: 27, rewrite: rewrite, titles: titles};

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
        var ids = trackTvids(args[0]);
        if (!ids.length) return callback.apply(self, args);
        return primeTranslationStates(ids).then(function () {
          args[0] = rewrite(args[0]);
          return callback.apply(self, args);
        });
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
        if (requestUrl(input).indexOf(SIDE + "/") === 0) return localFetch(input, init);
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
            return primeTranslationStates(ids).then(function () {
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
          this.__iqiyiSubtitleRequest = (this.__iqiyiSubtitleRequest || 0) + 1;
          this.__iqiyiSubtitleAsync = arguments[2] !== false;
          this.__iqiyiSubtitleSourceUrl = requestUrl(arguments[1]);
          return nativeOpen.apply(this, arguments);
        };
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
              localFetch(localUrl, {signal:relay.controller.signal}).then(function (response) {
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
    var VERSION = 4;
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
