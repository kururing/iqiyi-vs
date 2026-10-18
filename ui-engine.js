/* iqiyi-vi */
(function () {
  var ENGINE_VERSION = 105;
  var IS_PLAYER = /(^|\/)player(?:_mac)?\.html$/i.test(location.pathname);
  if (window.__iqiyiVi && window.__iqiyiViVersion === ENGINE_VERSION) {
    if (window.__iqiyiViReload) window.__iqiyiViReload(window.__iqiyiViDict);
    return;
  }
  if (window.__iqiyiViStop) window.__iqiyiViStop();
  var oldStyle = document.getElementById("iqiyi-vi-css");
  if (oldStyle) oldStyle.remove();
  var D = window.__iqiyiViDict || {};
  function keysOf() {
    return Object.keys(D)
      .filter(function (k) { return k.length >= 1; })
      .sort(function (a, b) { return b.length - a.length; });
  }
  var KEYS = keysOf();
  var LONG = KEYS;
  var TEXT_CACHE = new Map();
  var SKIP = { SCRIPT: 1, STYLE: 1, TEXTAREA: 1, NOSCRIPT: 1, CODE: 1 };
  // V4 contained mixed-language results caused by translating already-translated DOM text.
  var AUTO_KEY = "__iqiyiViAutoV10";
  var AUTO_CACHE = {};
  var AUTO_PENDING = {};
  var AUTO_QUEUE = [];
  var AUTO_ACTIVE = false;
  try { AUTO_CACHE = JSON.parse(localStorage.getItem(AUTO_KEY) || "{}"); } catch (e) {}

  function cjkCount(s) {
    var m = String(s || "").match(/[\u3400-\u9fff]/g);
    return m ? m.length : 0;
  }

  function saveAutoCache() {
    try { localStorage.setItem(AUTO_KEY, JSON.stringify(AUTO_CACHE)); } catch (e) {}
  }

  function applyAuto(text, translated) {
    var waiting = AUTO_PENDING[text] || [];
    delete AUTO_PENDING[text];
    for (var i = 0; i < waiting.length; i++) {
      var item = waiting[i];
      var node = item && item.node ? item.node : item;
      if (!node || !node.isConnected) continue;
      if (item && item.source != null && node.nodeType === 3 && node.nodeValue !== item.source) continue;
      if (item && item.set) {
        item.set(translated);
        continue;
      }
      if (!cjkCount(node.nodeValue)) continue;
      var lead = node.nodeValue.match(/^\s*/)[0];
      var tail = node.nodeValue.match(/\s*$/)[0];
      node.nodeValue = lead + translated + tail;
    }
  }

  function pumpAuto() {
    if (AUTO_ACTIVE || !AUTO_QUEUE.length || !window.fetch) return;
    AUTO_ACTIVE = true;
    var batch = [];
    var url = "https://clients5.google.com/translate_a/t?client=dict-chrome-ex&sl=zh-CN&tl=vi";
    while (AUTO_QUEUE.length && batch.length < 8) {
      var part = "&q=" + encodeURIComponent(AUTO_QUEUE[0]);
      if (batch.length && url.length + part.length > 5000) break;
      batch.push(AUTO_QUEUE.shift());
      url += part;
    }
    Promise.race([
      fetch(url),
      new Promise(function (_, reject) {
        setTimeout(function () { reject(new Error("timeout")); }, 8000);
      })
    ])
      .then(function (r) { return r.ok ? r.json() : Promise.reject(new Error("HTTP " + r.status)); })
      .then(function (data) {
        for (var i = 0; i < batch.length; i++) {
          var text = batch[i];
          var translated = data && data[i];
          if (translated && cjkCount(translated) === 0) {
            AUTO_CACHE[text] = translated;
            applyAuto(text, translated);
          } else {
            delete AUTO_PENDING[text];
          }
        }
        saveAutoCache();
      })
      .catch(function () {
        for (var i = 0; i < batch.length; i++) delete AUTO_PENDING[batch[i]];
      })
      .then(function () {
        AUTO_ACTIVE = false;
        setTimeout(pumpAuto, 250);
      });
  }

  function mostlyCjk(s) {
    var t = String(s || "").replace(/\s/g, "");
    if (!t) return false;
    return cjkCount(t) >= Math.max(1, t.length * 0.6);
  }

  function wordChar(ch) {
    return !!ch && /[A-Za-z0-9À-ỹĐđ\u3400-\u9fff]/.test(ch);
  }

  function replaceWithSpacing(source, find, replacement) {
    var out = "";
    var from = 0;
    var index;
    while ((index = source.indexOf(find, from)) !== -1) {
      var before = source.charAt(index - 1);
      var after = source.charAt(index + find.length);
      var left = before && (wordChar(before) || before === "|");
      var right = after && (wordChar(after) || after === "|");
      out += source.slice(from, index);
      if (left && !/\s$/.test(out) && !/^\s/.test(replacement)) out += " ";
      out += replacement;
      if (right && !/\s$/.test(replacement)) out += " ";
      from = index + find.length;
    }
    return from ? out + source.slice(from) : source;
  }

  function canTranslateWhole(s) {
    var text = String(s || "").replace(/\s/g, "");
    return cjkCount(text) >= 2 && (mostlyCjk(text) || text.length <= 80);
  }

  function autoTranslateMixed(node, value, setter) {
    var text = String(value || "");
    var patterned = trPatterns(text);
    if (patterned !== text && !cjkCount(patterned)) {
      if (setter) setter(patterned);
      else if (node && node.isConnected && node.nodeType === 3) node.nodeValue = patterned;
      return;
    }
    text = patterned;
    if (canTranslateWhole(text)) {
      autoTranslate(node, text, setter, true);
      return;
    }
    var matches = text.match(/[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]{2,}/g) || [];
    var seen = {};
    var current = text;
    for (var i = 0; i < matches.length; i++) {
      (function (part) {
        if (seen[part]) return;
        seen[part] = true;
        autoTranslate(node, part, function (translated) {
          current = replaceWithSpacing(current, part, trCompactFix(translated));
          if (setter) {
            setter(current);
          } else if (node && node.isConnected && node.nodeType === 3) {
            node.nodeValue = node.nodeValue.split(part).join(translated);
          }
        });
      })(matches[i]);
    }
  }

  function autoTranslate(node, value, setter, allowMixed) {
    if (!node || !value) return;
    var text = String(value).trim();
    // Only translate source text that is predominantly Chinese. This keeps
    // dictionary/pattern output from being translated a second time.
    if (!text || text.length > 180 || (!mostlyCjk(text) && !allowMixed)) return;
    var item = { node: node, set: setter || null, source: node.nodeType === 3 ? node.nodeValue : null };
    if (AUTO_CACHE[text]) {
      AUTO_PENDING[text] = [item];
      applyAuto(text, AUTO_CACHE[text]);
      return;
    }
    if (AUTO_PENDING[text]) {
      var known = AUTO_PENDING[text].some(function (entry) { return entry.node === node; });
      if (!known) AUTO_PENDING[text].push(item);
      return;
    }
    AUTO_PENDING[text] = [item];
    AUTO_QUEUE.push(text);
    pumpAuto();
  }

  window.__iqiyiViAutoStatus = function () {
    return {
      active: AUTO_ACTIVE,
      queued: AUTO_QUEUE.length,
      pending: Object.keys(AUTO_PENDING).length,
      cached: Object.keys(AUTO_CACHE).length
    };
  };

  function trPatterns(s) {
    return s
      .replace(/展开\s*(\d+)\s*条回复/g, "$1 trả lời")
      .replace(/收起\s*(\d+)\s*条回复/g, "$1 trả lời")
      .replace(/展开\s*(\d+)\s*条/g, "$1")
      .replace(/(\d+)\s*条回复/g, "$1 trả lời")
      .replace(/更新至第(\d+)集/g, "Cập nhật tới tập $1")
      .replace(/更新至(\d+)集/g, "Cập nhật tới tập $1")
      .replace(/更新至第(\d+)/g, "Cập nhật tới tập $1")
      .replace(/全(\d+)集/g, "$1 tập")
      .replace(/共(\d+)集/g, "$1 tập")
      .replace(/^第(\d+)集$/g, "Tập $1")
      .replace(/(\d+)集全/g, "$1 tập")
      .replace(/第(\d+)-(\d+)集/g, "Tập $1-$2")
      .replace(/限免第?(\d+)-(\d+)集/g, "Miễn phí tập $1-$2")
      .replace(/限免第?(\d+)集/g, "Miễn phí tập $1")
      .replace(/今日(\d{1,2}:\d{2})更新/g, "Cập nhật hôm nay lúc $1")
      .replace(/明日(\d{1,2}:\d{2})更新/g, "Cập nhật ngày mai lúc $1")
      .replace(/今日(\d{1,2}:\d{2})上线/g, "Phát hành hôm nay lúc $1")
      .replace(/明日(\d{1,2}:\d{2})上线/g, "Phát hành ngày mai lúc $1")
      .replace(/近(\d+)月上新/g, "Mới trong $1 tháng qua")
      .replace(/近(\d+)月转免/g, "Miễn phí trong $1 tháng qua")
      .replace(/近(\d+)周上新/g, "Mới trong $1 tuần qua")
      .replace(/弹幕破(\d+(?:\.\d+)?)万/g, function (_, n) {
        var total = Number(n) * 10000;
        if (total >= 1000000) return "Bình luận vượt " + (total / 1000000).toFixed(total % 1000000 ? 1 : 0) + " triệu";
        return "Bình luận vượt " + (total / 1000).toFixed(total % 1000 ? 1 : 0) + " nghìn";
      })
      .replace(/(\d+(?:\.\d+)?)万/g, function (_, n) {
        var total = Number(n) * 10000;
        if (total >= 1000000) return (total / 1000000).toFixed(total % 1000000 ? 1 : 0) + " triệu";
        return (total / 1000).toFixed(total % 1000 ? 1 : 0) + " nghìn";
      })
      .replace(/(\d+) 部新片/g, "$1 phim mới")
      .replace(/(\d+) 部短剧/g, "$1 phim ngắn")
      .replace(/(\d{2}-\d{2})期/g, "Kỳ $1")
      .replace(/(\d+)分钟/g, "$1 phút")
      .replace(/(\d+(?:\.\d+)?)分(?!钟)/g, "$1 điểm")
      .replace(/(\d{4})年/g, "Năm $1")
      .replace(/观看至第(\d+)集/g, "Đã xem tới tập $1")
      .replace(/第(\d+)集/g, "Tập $1")
      .replace(/第(\d+)季/g, "Mùa $1")
      .replace(/总榜No\.(\d+)/g, " - BXH tổng số $1")
      .replace(/剧榜No\.(\d+)/g, " - BXH phim số $1")
      .replace(/榜No\.(\d+)/g, " - BXH số $1")
      .replace(/剧榜No\.(\d+)/g, " - BXH phim số $1")
      .replace(/短剧榜No\.(\d+)/g, " - BXH phim ngắn số $1")
      .replace(/最高热度破(\d+)/g, "Độ hot cao nhất vượt $1")
      .replace(/最高热度破万/g, "Độ hot cao nhất vượt 10 nghìn")
      .replace(/不看：/g, "Không xem: ")
      .replace(/(\d+)人正在看/g, "$1 người đang xem")
      .replace(/(\d+\.?\d*)万人正在看/g, "$10k người đang xem")
      .replace(/(\d+)万次播放/g, "$10k lượt xem")
      .replace(/(\d+)亿次播放/g, "$100 triệu lượt xem")
      .replace(/(\d+)次播放/g, "$1 lượt xem")
      .replace(/(\d+)分钟前/g, "$1 phút trước")
      .replace(/(\d+)小时前/g, "$1 giờ trước")
      .replace(/(\d+)天前/g, "$1 ngày trước")
      .replace(/(\d+)秒后可/g, "$1 giây nữa có thể ")
      .replace(/(\d+)秒后/g, "$1 giây nữa")
      .replace(/会员专享/g, "Độc quyền VIP")
      .replace(/用券解锁/g, "Mở bằng vé");
  }

  var COMPACT_FIX = [
    ["Ngôi sao đang đến", "Star"],
    ["Ngôi sao đang", "Star"],
    ["Sáng tạo thứ hai", "Remix"],
    ["bàn luận", "Bàn"],
    ["Bàn luận", "Bàn"],
    ["Hot nhất", "Hot"],
    ["Mới nhất", "Mới"],
    ["Trả lời", "Trả"],
    ["Mở rộng", "Mở"],
    ["Openwidth", "Mở"],
    ["Hài kịchdanh sách vuamiệngmùaMùa 2", "Vua hài độc thoại mùa 2"],
    ["Hài kịchdanh sách vuamiệngmùa 2", "Vua hài độc thoại mùa 2"],
    ["MớiTrailer", "Mới · Trailer"],
    ["Ngày mailên sóng", "Ngày mai · lên sóng"],
    ["phim truyền hìnhHot", "Phim bộ · Hot"],
    ["Học đườnghoạt hình", "Học đường · Hoạt hình"],
    ["Yến Ni giơ bảng phản đốiCông sởquấy rối", "Yến Ni giơ bảng phản đối quấy rối nơi công sở"],
    ["Tạ Thanh Viên,biến ngày khai trương thành võ đài", "Tạ Thanh Viên biến ngày khai trương thành võ đài"],
    ["NgayPhát", "Phát ngay"],
    ["tậpthổ cẩm", "tập tuyển chọn"],
    ["Tuyệt vờitậpthổ cẩm", "Tuyệt vời · tập tuyển chọn"],
    ["sinhNgày đang đến", "Ngày sinh đang đến"],
    ["Tạ Thanh Nguyênbiến", "Tạ Thanh Nguyên biến"],
    ["Tìm kiếm đảo hoangsinh，Xây dựng nơi trú ẩn từ đầu", "Sinh tồn trên đảo hoang, xây dựng nơi trú ẩn từ đầu"],
    ["ngàykỷ luật khiêu vũ", "Ngày kỷ luật khiêu vũ"],
    ["KHÔNGkểmọi người", "Không thể nói cho người khác"],
    ["Cúc Tịnh YTrần Triết Nguyên", "Cúc Tịnh Y · Trần Triết Nguyên"],
    ["Hứa KhảiNgô Gia Nghĩa", "Hứa Khải · Ngô Gia Nghĩa"],
    ["ngàyTôn trọng huyền thoại", "Tôn trọng huyền thoại"],
    ["Tuyệt vờiPhim ngắnThìCó con đâyiQIYI", "Tuyệt vời · Phim ngắn · Xem ngay trên iQIYI"],
    ["Yêu cầu ngày tận thếsinh", "Sinh tồn sau ngày tận thế"],
    ["phim mớiSắp chiếu rạp", "phim mới · Sắp chiếu rạp"],
    ["Hứa KhảiWu Jiayi", "Hứa Khải · Ngô Gia Nghĩa"],
    ["Bạch LộcHứa Khải", "Bạch Lộc · Hứa Khải"],
    ["Cúc Tịnh YQuách Tuấn Thần", "Cúc Tịnh Y · Quách Tuấn Thần"],
    ["Ao Thụy BằngJenny Sun", "Ao Thụy Bằng · Jenny Sun"],
    ["Vương Tử KỳQuan Hiểu Đồng", "Vương Tử Kỳ · Quan Hiểu Đồng"],
    ["Yến NiĐặng Ân Hi", "Yến Ni · Đặng Ân Hi"],
    ["Nhậm Gia LuânTần Tuấn Kiệt", "Nhậm Gia Luân · Tần Tuấn Kiệt"],
    ["Trương Nhất SơnLý Mộc Thần", "Trương Nhất Sơn · Lý Mộc Thần"],
    ["ngày Tôn trọng huyền thoại", "Tôn trọng huyền thoại"],
    ["Tuyệt vời Phim ngắn Thì Có con đây iQIYI", "Tuyệt vời · Phim ngắn · Xem ngay trên iQIYI"],
    ["Hài kịch danh sách vua miệng mùa Mùa 2", "Vua hài độc thoại mùa 2"],
    ["Yến Ni giơ bảng phản đối Công sở quấy rối", "Yến Ni giơ bảng phản đối quấy rối nơi công sở"]
  ];

  function trCompactFix(s) {
    var t = s;
    for (var i = 0; i < COMPACT_FIX.length; i++) t = t.split(COMPACT_FIX[i][0]).join(COMPACT_FIX[i][1]);
    return t;
  }

  function tr(s) {
    if (!s) return s;
    var source = String(s);
    if (TEXT_CACHE.has(source)) return TEXT_CACHE.get(source);
    var translated = translateText(source);
    if (TEXT_CACHE.size >= 2000) TEXT_CACHE.delete(TEXT_CACHE.keys().next().value);
    TEXT_CACHE.set(source, translated);
    return translated;
  }

  function translateText(s) {
    var orig = String(s);
    var lead = orig.match(/^\s*/)[0];
    var tail = orig.match(/\s*$/)[0];
    var t = orig.slice(lead.length, orig.length - tail.length);
    if (!t) return orig;
    if (D[t]) return lead + trCompactFix(D[t]) + tail;
    var p = trPatterns(t);
    if (p !== t && !/[\u4e00-\u9fff]/.test(p)) return lead + trCompactFix(p) + tail;
    if (p !== t) t = p;
    if (t.length <= 180 && /[\u4e00-\u9fff]/.test(t)) {
      for (var i = 0; i < LONG.length; i++) {
        if (t.indexOf(LONG[i]) !== -1) t = replaceWithSpacing(t, LONG[i], D[LONG[i]]);
      }
    }
    t = trCompactFix(t);
    return lead + t + tail;
  }

  function injectCSS() {
    if (!document.documentElement || document.getElementById("iqiyi-vi-css")) return;
    var s = document.createElement("style");
    s.id = "iqiyi-vi-css";
    s.textContent =
      'img[src*="/watermark_rightTop"],img[src*="/watermark_rightBottom"]{display:none!important;}' +
      'html[lang="vi"] { overflow-wrap:normal; }' +
      'html[lang="vi"] [class*="tabName"],' +
      'html[lang="vi"] [class*="tagName"],' +
      'html[lang="vi"] [class*="tagHeader"],' +
      'html[lang="vi"] [class*="mainTabs"] span,' +
      'html[lang="vi"] [class*="comments_filter"],' +
      'html[lang="vi"] [class*="comments_replyBtn"],' +
      'html[lang="vi"] [class*="comments_expandBtn"],' +
      'html[lang="vi"] [class*="tabMenu_title"],' +
      'html[lang="vi"] [class*="tabMenu_tabItem"],' +
      'html[lang="vi"] [class*="side_item"],' +
      'html[lang="vi"] [class*="side_sideText"],' +
      'html[lang="vi"] [class*="filterTab"],' +
      'html[lang="vi"] [class*="sortTab"],' +
      'html[lang="vi"] [data-iqiyi-vi-fit="1"]{' +
      "white-space:nowrap!important;overflow:hidden!important;text-overflow:ellipsis;word-break:keep-all;}" +
      '#pcaSubtitleContainer,#pcaSubtitleContainer *,.caption-main,.caption-main *{' +
      'font-family:Arial,Helvetica,sans-serif!important;font-weight:700!important;color:#fff!important;' +
      '-webkit-text-stroke:1.2px #111!important;paint-order:stroke fill;' +
      'text-shadow:0 1px 1px #111,1px 0 1px #111,-1px 0 1px #111,0 -1px 1px #111,0 2px 4px #000!important;}' +
      'video::cue{font-family:Arial,Helvetica,sans-serif;font-weight:700;color:#fff;background:transparent;' +
      'text-shadow:0 1px 1px #111,1px 0 1px #111,-1px 0 1px #111,0 -1px 1px #111,0 2px 4px #000;}';
    (document.head || document.documentElement).appendChild(s);
  }

  function setDirectText(el, next) {
    // React owns the DOM structure; replacing text nodes breaks its next commit.
    if (el.childNodes.length === 1 && el.firstChild.nodeType === 3) {
      el.firstChild.nodeValue = next;
    }
  }

  function compactTranslate(el) {
    if (!el || el.nodeType !== 1 || el.id === "pcaSubtitleContainer") return false;
    if (el.childNodes.length !== 1 || el.firstChild.nodeType !== 3) return false;
    var all = (el.textContent || "").replace(/\s+/g, " ").trim();
    if (!all || all.length > 36) return false;
    if (!/[\u3400-\u9fff]/.test(all)) return false;
    var next = tr(all);
    if (next === all) return false;
    setDirectText(el, next);
    fitCompact(el);
    return true;
  }


  function translateDocumentTitle() {
    var title = document.querySelector("title");
    if (!title) return;
    var raw = title.textContent || "";
    var next = tr(raw);
    if (next !== raw && title.firstChild && title.firstChild.nodeType === 3) title.firstChild.nodeValue = next;
    if (cjkCount(next) && title.firstChild) {
      autoTranslateMixed(title.firstChild, next, function (translated) {
        if ((title.textContent || "") === next && title.firstChild && title.firstChild.nodeType === 3) title.firstChild.nodeValue = translated;
      });
    }
  }

  function fitCompact(node) {
    var el = node && node.nodeType === 3 ? node.parentElement : node;
    if (!el || el.nodeType !== 1 || el.childElementCount) return;
    if (el.id === "pcaSubtitleContainer") return;
    var text = (el.innerText || "").replace(/\s+/g, " ").trim();
    if (!text || text.length > 120) return;
    var fs = parseFloat((window.getComputedStyle(el).fontSize) || "12") || 12;
    var parent = el.parentElement;
    if (parent && parent.clientWidth > 0 && el.clientWidth > parent.clientWidth + 2) {
      el.style.maxWidth = "100%";
      el.style.boxSizing = "border-box";
    }
    if (el.clientHeight > 4 && el.clientHeight <= fs * 1.85 && el.scrollWidth <= el.clientWidth + 2) return;
    if (el.scrollHeight <= el.clientHeight + 2 && el.scrollWidth <= el.clientWidth + 2) return;
    el.setAttribute("data-iqiyi-vi-fit", "1");
    el.style.whiteSpace = "nowrap";
    el.style.overflow = "hidden";
    var size = fs;
    while (size > 9 && (el.scrollWidth > el.clientWidth + 1 || el.scrollHeight > el.clientHeight + 1)) {
      size -= 0.5;
      el.style.fontSize = size + "px";
    }
    if (el.scrollWidth > el.clientWidth + 1) {
      el.style.textOverflow = "ellipsis";
      if (!el.title) el.title = text;
    }
  }

  function walk(node) {
    if (!node) return;
    if (node.nodeType === 3) {
      var raw = node.nodeValue;
      var next = tr(raw);
      if (next !== raw) node.nodeValue = next;
      if (cjkCount(next)) autoTranslateMixed(node, canTranslateWhole(raw) ? raw : next);
      else fitCompact(node);
      return;
    }
    if (node.nodeType !== 1 || SKIP[node.tagName] || node.id === "pcaSubtitleContainer" || /subtitleContainer|caption-main/i.test(String(node.className || "") + " " + node.id)) return;
    if (node.shadowRoot) walk(node.shadowRoot);
    if (node.tagName === "HTML" && node.getAttribute("lang") === "zh") node.setAttribute("lang", "vi");
    var cls = String(node.className || "");
    var joined = (node.textContent || "").replace(/\s+/g, "");
    var chipLike = node.childElementCount > 0 && node.childElementCount <= 6 &&
      ((node.clientHeight > 0 && node.clientHeight <= 48) ||
        /tabName|tagName|tagHeader|chip|sort|filter|reply|hot/i.test(cls) ||
        /展开\d+条|条回复|最热|最新|明星在追|二次创作/.test(joined));
    if (chipLike && compactTranslate(node)) return;
    ["title", "placeholder", "aria-label", "alt", "value"].forEach(function (a) {
      if (a === "value" && node.tagName !== "INPUT" && node.tagName !== "BUTTON") return;
      var v = node.getAttribute && node.getAttribute(a);
      if (!v && a === "value" && node.value) v = node.value;
      if (!v) return;
      var n = tr(v);
      if (n !== v) {
        if (a === "value" && "value" in node) node.value = n;
        else node.setAttribute(a, n);
      } else if (cjkCount(v)) {
        autoTranslateMixed(node, v, function (translated) {
          if (node.getAttribute(a) === v) {
            if (a === "value" && "value" in node) node.value = translated;
            else node.setAttribute(a, translated);
          }
        });
      }
    });
    if (node.tagName === "META" && /^(description|keywords)$/i.test(node.getAttribute("name") || "")) {
      var content = node.getAttribute("content");
      if (content) {
        var translatedContent = tr(content);
        if (translatedContent !== content) node.setAttribute("content", translatedContent);
      }
    }
    var kids = node.childNodes;
    var hasEl = false;
    for (var i = 0; i < kids.length; i++) {
      if (kids[i].nodeType === 1) { hasEl = true; break; }
    }
    if (!hasEl && kids.length === 1 && kids[0].nodeType === 3) {
      var all = node.textContent;
      var t = tr(all);
      if (t !== all) kids[0].nodeValue = t;
      if (cjkCount(t) && node.firstChild && node.firstChild.nodeType === 3) {
        autoTranslateMixed(node.firstChild, canTranslateWhole(all) ? all : t);
      } else {
        fitCompact(node);
      }
      return;
    }
    for (var j = 0; j < kids.length; j++) walk(kids[j]);
  }

  function run() {
    try {
      injectCSS();
      translateDocumentTitle();
      document.querySelectorAll('[data-iqiyi-vi-fit="1"]').forEach(function (el) {
        if (!el.childElementCount) return;
        el.removeAttribute("data-iqiyi-vi-fit");
        if (String(el.className).indexOf("settingBtnAnchor") !== -1) el.removeAttribute("title");
        ["whiteSpace", "overflow", "fontSize", "textOverflow", "maxWidth", "boxSizing"].forEach(function (key) {
          el.style[key] = "";
        });
      });
      walk(document.documentElement || document.body);
    } catch (e) {}
  }

  window.__iqiyiVi = true;
  window.__iqiyiViVersion = ENGINE_VERSION;
  window.__iqiyiViReload = function (next) {
    if (next) {
      D = next;
      window.__iqiyiViDict = next;
      KEYS = keysOf();
      LONG = KEYS;
      TEXT_CACHE.clear();
    }
    run();
  };

  if (document.body) run();
  else document.addEventListener("DOMContentLoaded", run);
  var runTimer = setInterval(run, 1500);
  var obs;
  try {
    obs = new MutationObserver(function () {
      if (run._t) cancelAnimationFrame(run._t);
      run._t = requestAnimationFrame(run);
    });
    obs.observe(document.documentElement, { childList: true, subtree: true, characterData: true });
  } catch (e) {}
  window.__iqiyiViStop = function () {
    clearInterval(runTimer);
    if (obs) obs.disconnect();
    if (run._t) cancelAnimationFrame(run._t);
  };
})();
