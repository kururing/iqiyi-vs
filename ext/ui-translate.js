/* Missing UI copy only. No browser/session credentials leave this worker. */
const uiTranslationCache = new Map();
const uiTranslationPending = new Map();
function uiTranslationBatch(texts) {
  if (!Array.isArray(texts) || !texts.length || texts.length > 8 ||
      texts.some(text => typeof text !== "string" || !text.trim() || text.length > 500)) {
    return Promise.reject(new Error("Invalid UI translation batch"));
  }
  const key = JSON.stringify(texts);
  if (uiTranslationCache.has(key)) return Promise.resolve(uiTranslationCache.get(key));
  if (uiTranslationPending.has(key)) return uiTranslationPending.get(key);
  const params = new URLSearchParams({client:"dict-chrome-ex", sl:"zh-CN", tl:"vi"});
  texts.forEach(text => params.append("q", text));
  const work = fetch("https://clients5.google.com/translate_a/t?" + params, {
    credentials:"omit", signal:AbortSignal.timeout(8000)
  }).then(response => {
    if (!response.ok) throw new Error("Translation HTTP " + response.status);
    return response.json();
  }).then(result => {
    if (!Array.isArray(result) || result.length !== texts.length ||
        result.some(text => typeof text !== "string" || !text.trim())) {
      throw new Error("Invalid UI translation response");
    }
    if (uiTranslationCache.size >= 256) uiTranslationCache.delete(uiTranslationCache.keys().next().value);
    uiTranslationCache.set(key, result);
    return result;
  }).finally(() => uiTranslationPending.delete(key));
  uiTranslationPending.set(key, work);
  return work;
}
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message || message.type !== "iqiyi-vi-translate") return;
  try {
    const url = new URL(sender.origin || sender.url || "");
    if (!sender.tab || url.protocol !== "https:" || !/(^|\.)iqiyi\.com$/i.test(url.hostname)) {
      sendResponse({error:"Untrusted UI translation sender"});
      return;
    }
  } catch (_) { sendResponse({error:"Invalid UI translation sender"}); return; }
  uiTranslationBatch(message.texts).then(translations => sendResponse({translations}),
    error => sendResponse({error:error.message}));
  return true;
});
