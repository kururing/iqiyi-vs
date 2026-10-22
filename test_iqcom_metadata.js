// Run with: node test_iqcom_metadata.js
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const settle = () => new Promise(resolve=>setImmediate(resolve));

async function metadataChecks() {
  let pending = [], active = 0, peak = 0, started = 0, now = 1000, failures = 0, misses = 0;
  const context = {
    window:{fetch:true,__iqiyiViToken:"test-token"},
    document:{getElementById:()=>null},
    location:{pathname:"/",href:"https://www.iqiyi.com/"},
    localStorage:{length:0,getItem:()=>"{}"},
    Date:{now:()=>now},
    fetch(url) {
      if (url.endsWith("error")) {failures++;return Promise.reject(Error("offline"));}
      if (url.endsWith("miss")) {misses++;return Promise.resolve({ok:true,json:async()=>({retryAfterMs:10000})});}
      started++;active++;peak=Math.max(peak,active);
      return new Promise(resolve=>pending.push(()=>{active--;resolve({ok:true,json:async()=>({name:"Actor"})});}));
    }
  };
  let source=fs.readFileSync(__dirname+"/ui-engine.js","utf8");
  source=source.slice(0,source.indexOf("  function run()"))+
    "globalThis.request=requestIqcomMetadata;globalThis.wait=waitForIqcomMetadata;})();";
  vm.runInNewContext(source,context);
  const requests=Array.from({length:12},(_,i)=>context.request("international-actor?name="+i));
  assert.equal(context.request("international-actor?name=0"),requests[0]);
  await settle();
  assert.equal(started,4);
  while(pending.length) {const batch=pending.splice(0);batch.forEach(resolve=>resolve());await settle();}
  await Promise.all(requests);
  assert.equal(started,12);
  assert.equal(peak,4);
  await context.request("international-actor?name=0");
  assert.equal(started,12);
  const node={isConnected:true};
  let loads=0,applied=0;
  for(let i=0;i<100;i++) context.wait(node,"title","same",()=>{loads++;return Promise.resolve({});},()=>applied++);
  await settle();
  assert.equal(loads,1);
  assert.equal(applied,1);
  for(const field of ["title","alt","text"]) context.wait(node,field,"same",()=>Promise.resolve({}),()=>applied++);
  await settle();
  assert.equal(applied,4,"Different attributes must each receive their own result");
  await context.request("error");
  await context.request("error");
  assert.equal(failures,1);
  now+=15001;
  await context.request("error");
  assert.equal(failures,2);
  await context.request("miss");
  now+=9999;
  await context.request("miss");
  assert.equal(misses,1);
  now+=2;
  await context.request("miss");
  assert.equal(misses,2,"Server retry timing must survive the frontend cache");
}

async function cookieChecks() {
  let changed, timer, syncingPost, posts=0;
  const cookies=[{name:"test",value:"synthetic",domain:".iq.com"}];
  const context={
    setTimeout(fn) {timer=fn;return 1;}, clearTimeout() {timer=null;},
    AbortSignal:{timeout:()=>undefined},
    chrome:{
      runtime:{getURL:path=>"extension-test/"+path,onMessage:{addListener:()=>{}}},
      storage:{local:{get:async()=>({iqcomSourceId:"synthetic-source-id"})}},
      cookies:{getAll:async()=>cookies,onChanged:{addListener:fn=>{changed=fn;}}},
      alarms:{onAlarm:{addListener:()=>{}},create:()=>{}}
    },
    fetch:async(url)=>{
      if(url.startsWith("extension-test/")) return {ok:true,json:async()=>({sessionToken:"test"})};
      posts++;
      if(syncingPost) await syncingPost;
      return {ok:true,json:async()=>({synced:true})};
    }
  };
  vm.runInNewContext(fs.readFileSync(__dirname+"/ext/iqcom-session.js","utf8"),context);
  await settle();
  assert.equal(posts,1);
  for(let i=0;i<100;i++) changed({cookie:{domain:".iq.com"}});
  assert.equal(posts,1);
  let release;
  syncingPost=new Promise(resolve=>{release=resolve;});
  timer();
  await settle();
  assert.equal(posts,2);
  // A cookie update arriving during the request must be sent after that request finishes.
  changed({cookie:{domain:".iq.com"}});
  timer();
  await settle();
  assert.equal(posts,2);
  release();syncingPost=null;
  await settle();await settle();
  assert.equal(posts,3);
}

(async()=>{
  await metadataChecks();
  await cookieChecks();
  console.log("Metadata queue/cache/waiter and cookie burst checks passed.");
})().catch(error=>{console.error(error);process.exitCode=1;});
