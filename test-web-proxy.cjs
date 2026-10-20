const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

(async () => {
  const listeners = {};
  let proxy = {host: "proxy.example", port: 8888, username: "user", password: "p@ss"};
  let settings = {levelOfControl: "controllable_by_this_extension", value: {mode: "system"}};
  let available = true, setCount = 0, clearCount = 0;
  const event = name => ({addListener(fn) { listeners[name] = fn; }});
  const context = vm.createContext({URL, AbortSignal, console,
    fetch: async url => {
      if (url.startsWith("chrome-extension:")) return {ok: true, json: async () => ({token: "test-token"})};
      if (!available) throw Error("offline");
      return {ok: true, json: async () => ({proxy})};
    },
    chrome: {
      runtime: {getURL: path => "chrome-extension://test/" + path},
      proxy: {settings: {
        get: async () => settings,
        set: async ({value}) => { setCount++; settings = {levelOfControl: "controlled_by_this_extension", value}; },
        clear: async () => { clearCount++; settings = {levelOfControl: "controllable_by_this_extension", value: {mode: "system"}}; }
      }},
      alarms: {create() {}, onAlarm: event("alarm")},
      webRequest: {onAuthRequired: event("auth"), onCompleted: event("done"), onErrorOccurred: event("error")}
    }
  });
  vm.runInContext(fs.readFileSync("ext/proxy.js", "utf8"), context);
  await vm.runInContext("syncProxy()", context);
  const pac = vm.createContext({});
  vm.runInContext(settings.value.pacScript.data, pac);
  for (const host of ["iqiyi.com", "www.iqiyi.com", "cache.video.iqiyi.com", "www.iq.com", "data.video.qiyi.com", "img.qy.net", "WWW.IQIYI.COM."]) {
    assert.equal(pac.FindProxyForURL("https://" + host + "/", host), "PROXY proxy.example:8888");
  }
  for (const host of ["127.0.0.1", "localhost", "google.com", "fakeiqiyi.com", "iqiyi.com.evil.example"]) {
    assert.equal(pac.FindProxyForURL("https://" + host + "/", host), "DIRECT");
  }
  assert(!settings.value.pacScript.data.includes("p@ss"));
  settings.value = {pacScript: {data: settings.value.pacScript.data, mandatory: true}, mode: "pac_script"};
  await vm.runInContext("syncProxy()", context);
  assert.equal(setCount, 1, "unchanged proxy must not reset active connections");
  const auth = overrides => new Promise(resolve => listeners.auth({requestId: "one", isProxy: true,
    url: "https://www.iqiyi.com/", challenger: {host: "proxy.example", port: 8888}, ...overrides}, resolve));
  assert.equal(JSON.stringify(await auth({})), JSON.stringify({authCredentials: {username: "user", password: "p@ss"}}));
  assert.equal((await auth({})).cancel, true, "bad credentials must not loop");
  listeners.done({requestId: "one"});
  for (const override of [{isProxy: false}, {url: "https://evil.example/"}, {challenger: {host: "evil.example", port: 8888}}]) {
    assert.equal(JSON.stringify(await auth(override)), "{}");
  }
  available = false;
  await assert.rejects(vm.runInContext("syncProxy()", context));
  assert.equal(clearCount, 0, "a temporary manager failure must preserve proxy settings");
  available = true;
  proxy = {...proxy, host: "2001:db8::1"};
  await vm.runInContext("syncProxy()", context);
  vm.runInContext(settings.value.pacScript.data, pac);
  assert.equal(pac.FindProxyForURL("https://iqiyi.com/", "iqiyi.com"), "PROXY [2001:db8::1]:8888");
  proxy = null;
  await vm.runInContext("syncProxy()", context);
  assert.equal(clearCount, 1);
  settings.levelOfControl = "controlled_by_other_extensions";
  await vm.runInContext("syncProxy()", context);
  assert.equal(clearCount, 1, "must not clear another extension's proxy");
  proxy = {host: "proxy.example", port: 8888};
  await assert.rejects(vm.runInContext("syncProxy()", context));
  console.log("PASS: web/CDN routing, local bypass, proxy auth, retries, sync and disable");
})().catch(error => { console.error(error); process.exitCode = 1; });
