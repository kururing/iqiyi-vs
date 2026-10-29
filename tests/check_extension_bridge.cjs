/* Run: node tests/check_extension_bridge.cjs */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname,'../ext/iqcom-bootstrap.js'),'utf8');
function fixture() {
  let alive=true, mode='ready', timerId=0, failures=0, pauses=0;
  const timers=new Map(), calls=[];
  const runtime={get id(){return alive?'test-extension':undefined},lastError:null,
    sendMessage(message,reply){
      calls.push(message);
      if(message.type==='iqiyi-local-cancel'){reply({});return;}
      if(mode==='invalid')throw Error('Extension context invalidated.');
      if(mode==='unavailable'){
        runtime.lastError={message:'Could not establish connection. Receiving end does not exist.'};
        reply();runtime.lastError=null;return;
      }
      if(mode==='retry'&&failures++===0){
        runtime.lastError={message:'Could not establish connection. Receiving end does not exist.'};
        reply();runtime.lastError=null;return;
      }
      if(mode==='server-error'){reply({error:'Không lấy được dữ liệu.',code:'UPSTREAM'});return;}
      reply({status:200,headers:{'Content-Type':'application/json'},body:JSON.stringify(
        message.path==='/api/extension-token'?{token:'test-token'}:{translations:['Nhãn thử']})});
    }};
  const location={hostname:'www.iqiyi.com',protocol:'https:',origin:'https://www.iqiyi.com',href:'https://www.iqiyi.com/u/'};
  const window={addEventListener(){},postMessage(){},__iqiyiViPauseNetwork(){pauses++}};
  vm.runInNewContext(source,{window,location,document:{referrer:''},chrome:{runtime},URL,Response,Error,Object,
    crypto:{randomUUID:()=>String(calls.length+1)},
    setTimeout:(fn,ms)=>{timers.set(++timerId,{fn,ms});return timerId},clearTimeout:id=>timers.delete(id)});
  return {window,calls,timers,get pauses(){return pauses},invalidate(){alive=false},setMode:value=>{mode=value;failures=0},
    tick(){for(const[id,timer]of [...timers])if(timer.ms<1000){timers.delete(id);timer.fn()}},
    request:signal=>window.__iqiyiViLocalFetch('http://127.0.0.1:18766/api/localize-remaining',{method:'POST',body:'{}',signal})};
}
const flush=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
  const f=fixture();await flush();
  f.setMode('retry');
  const retry=f.request();f.tick();
  assert.deepEqual(await(await retry).json(),{translations:['Nhãn thử']});
  assert.equal(f.calls.filter(c=>c.path==='/api/localize-remaining').length,2,'Retry a waking worker once instead of reporting a subtitle app failure');
  f.invalidate();const count=f.calls.length;
  await assert.rejects(f.request(),e=>e.code==='EXTENSION_CONTEXT_INVALIDATED');
  await assert.rejects(f.request(),e=>e.code==='EXTENSION_CONTEXT_INVALIDATED');
  assert.equal(f.calls.length,count,'An invalid context never keeps calling chrome.runtime');
  assert.equal(f.pauses,1,'Pause pending work once');
  assert.equal(f.window.__iqiyiViBridgeExpired,true);
  assert.equal(f.window.__iqiyiViPublicApi,false);
  const thrown=fixture();await flush();thrown.setMode('invalid');
  await assert.rejects(thrown.request(),e=>e.code==='EXTENSION_CONTEXT_INVALIDATED');
  assert.equal(thrown.pauses,1,'Also handle Chrome throwing before the callback');
  const server=fixture();await flush();server.setMode('server-error');
  await assert.rejects(server.request(),e=>e.code==='UPSTREAM');
  assert.equal(server.calls.filter(c=>c.path==='/api/localize-remaining').length,1,'Do not retry application errors');
  const unavailable=fixture();await flush();unavailable.setMode('unavailable');
  const failure=assert.rejects(unavailable.request(),e=>e.code==='EXTENSION_BRIDGE_UNAVAILABLE');
  unavailable.tick();unavailable.tick();await failure;
  assert.equal(unavailable.calls.filter(c=>c.path==='/api/localize-remaining').length,3,'Stop after two worker wakeup retries');
  assert.equal(unavailable.pauses,0,'A temporarily unavailable worker does not expire the content context');
  const cancelled=fixture();await flush();cancelled.setMode('retry');
  const controller=new AbortController(),pending=cancelled.request(controller.signal);
  controller.abort(Error('cancelled'));
  await assert.rejects(pending,/cancelled/);cancelled.tick();
  assert.equal(cancelled.calls.filter(c=>c.path==='/api/localize-remaining').length,1,'Aborting cancels the delayed retry');
  console.log('Extension bridge checks passed: worker wakeup, invalidation, repeated calls, thrown errors, application errors and cancellation.');
})().catch(error=>{console.error(error);process.exitCode=1});
