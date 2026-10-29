/* Media stays in the extension origin; its worker serves seekable iq.com audio. */
(() => {
  const audio = new Audio();
  audio.preload = "metadata";
  let port, seekTarget = null;
  function state(event) {
    port?.postMessage({event, state:{paused:audio.paused,currentTime:audio.currentTime,
      readyState:audio.readyState,seeking:audio.seeking || seekTarget !== null,
      error:audio.error && {code:audio.error.code}}});
  }
  function source(value) {
    const url = new URL(value);
    if (url.protocol === "chrome-extension:" && url.host === location.host && url.pathname === "/audio-stream.mp4" &&
        !url.username && !url.password && !url.hash && /^\d{8,24}$/.test(url.searchParams.get("tvid") || "") &&
        /^[a-f0-9-]{36}$/.test(url.searchParams.get("stream") || "")) return url.href;
    if (url.origin !== "http://127.0.0.1:18766" || url.username || url.password || url.pathname !== "/audio.mp4" || url.hash ||
        !/^\d{8,24}$/.test(url.searchParams.get("tvid") || "") ||
        !/^[A-Za-z0-9_-]{16,80}$/.test(url.searchParams.get("stream") || "") ||
        !/^[a-f0-9]{64}$/.test(url.searchParams.get("token") || "")) throw Error("Invalid audio source");
    return url.href;
  }
  window.addEventListener("message", event => {
    let origin;
    try { origin = new URL(event.origin); } catch { return; }
    if (port || event.source !== parent || event.data?.type !== "iqiyi-audio-connect" ||
        event.ports.length !== 1 || origin.protocol !== "https:" || origin.port ||
        !(origin.hostname === "iqiyi.com" || origin.hostname.endsWith(".iqiyi.com"))) return;
    port = event.ports[0];
    port.onmessage = async ({data}) => {
      try {
        if (data.type === "load") {
          seekTarget = null;
          if (data.src) audio.src = source(data.src); else audio.removeAttribute("src");
          audio.load();
        } else if (data.type === "seek" && Number.isFinite(data.time) && data.time >= 0) {
          seekTarget = data.time;
          if (audio.readyState) { audio.currentTime = seekTarget; seekTarget = null; }
        } else if (data.type === "config") {
          if (typeof data.muted === "boolean") audio.muted = data.muted;
          if (Number.isFinite(data.volume)) audio.volume = Math.max(0, Math.min(1, data.volume));
          if (Number.isFinite(data.rate) && data.rate >= .25 && data.rate <= 4) audio.playbackRate = data.rate;
        } else if (data.type === "play") {
          await audio.play();
          port.postMessage({requestId:data.requestId});
        } else if (data.type === "pause") audio.pause();
        state();
      } catch (error) {
        if (data.requestId) port.postMessage({requestId:data.requestId,error:{name:error.name,message:error.message}});
        else state("error");
      }
    };
    port.start();
    port.postMessage({ready:true});
  });
  audio.addEventListener("loadedmetadata", () => {
    if (seekTarget !== null) { audio.currentTime = seekTarget; seekTarget = null; }
    state();
  });
  for (const event of ["waiting","error","playing","pause","seeked","canplay","ended"]) {
    audio.addEventListener(event, () => state(event));
  }
  setInterval(() => { if (port) state(); }, 200);
  window.addEventListener("pagehide", () => { audio.pause(); port?.close(); });
})();
