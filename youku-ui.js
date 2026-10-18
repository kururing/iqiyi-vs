/* Youku-only layout fixes; known labels are translated by youku-vi.json. */
(function (root) {
  "use strict";
  if (!root || !root.document) return;
  root.__youkuViEntry = true;
  var id = "youku-vi-layout";
  var style = document.getElementById(id) || document.createElement("style");
  style.id = id;
  style.textContent =
    '#ykPlayer [com="watermark"]{display:none!important;}' +
    ".leftnav_nav_mark{display:flex!important;align-items:center!important;height:48px!important;max-height:48px!important;overflow:hidden!important}" +
    ".leftnav_nav_mark>span{display:block!important;max-width:100%!important;white-space:nowrap!important;overflow:hidden!important;text-overflow:ellipsis!important}" +
    "[class*=pack_mark_],[class*=pack_mark_]>span{white-space:nowrap!important;overflow:hidden!important;text-overflow:ellipsis!important}" +
    ".kui-subtitle-subtitle-container,.kui-subtitle-subtitle-container *{" +
    "font-family:Arial,Helvetica,sans-serif!important;font-weight:700!important;color:#fff!important;" +
    "-webkit-text-stroke:1.2px #111!important;paint-order:stroke fill;" +
    "text-shadow:0 1px 1px #111,1px 0 1px #111,-1px 0 1px #111,0 -1px 1px #111,0 2px 4px #000!important;}";
  if (!style.isConnected) (document.head || document.documentElement).appendChild(style);
})(window);
