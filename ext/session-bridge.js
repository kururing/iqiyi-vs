/* Only the local manager can ask the worker to check this browser's iq.com session. */
window.addEventListener("message", event => {
  if (event.source !== window || event.origin !== location.origin ||
      event.data?.type !== "iqcom-session-check" || typeof event.data.requestId !== "string") return;
  const requestId = event.data.requestId;
  const unavailable = {error: "Tải lại tiện ích Việt hóa và trang này để kiểm tra phiên iq.com."};
  const reply = result => window.postMessage({type: "iqcom-session-result", requestId, ...result}, location.origin);
  try {
    const runtime = globalThis.chrome?.runtime;
    if (typeof runtime?.sendMessage !== "function") return reply(unavailable);
    runtime.sendMessage({type: "iqcom-session-check"}, result => {
      reply(runtime.lastError || !result ? unavailable : result);
    });
  } catch {
    // Reloading the extension invalidates content scripts in already open pages.
    reply(unavailable);
  }
});
