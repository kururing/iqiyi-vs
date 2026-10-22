// Run: node test_machine_fallback.js
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const settle = () => new Promise(resolve => setImmediate(resolve));
let timers = new Map(), sequence = 0, requests = [], respond;
const context = {
  window:{fetch:true}, document:{getElementById:()=>null},
  location:{pathname:'/',href:'https://www.iqiyi.com/'}, localStorage:{length:0},
  AbortController, Date,
  setTimeout(fn,ms){const id=++sequence;timers.set(id,{fn,ms});return id;},
  clearTimeout(id){timers.delete(id);},
  fetch(url,options){requests.push({url,options});return new Promise(resolve=>respond=resolve);}
};
let source=fs.readFileSync(__dirname+'/ui-engine.js','utf8');
source=source.slice(0,source.indexOf('  function run()'))+'globalThis.translate=autoTranslate;})();';
vm.runInNewContext(source,context);
function text(value,cls='',tag='SPAN') {
  const el={nodeType:1,tagName:tag,className:cls,getAttribute:()=>null,closest:()=>null};
  return {nodeType:3,nodeValue:value,isConnected:true,parentElement:el};
}
function pump(){for(const [id,timer] of timers) if(timer.ms<1000){timers.delete(id);timer.fn();return;}}
(async()=>{
  const fixed=text('正片');context.translate(fixed,fixed.nodeValue);
  assert.equal(fixed.nodeValue,'Tập chính');assert.equal(timers.size,0);
  for(const [cls,tag] of [['filmFeed_title__test','SPAN'],['feedZaizhui_itemTitle__test','SPAN'],['filmFeed_actName__test','SPAN'],['','INPUT']]) {
    const node=text('未知姓名',cls,tag);context.translate(node,node.nodeValue);
  }
  assert.equal(timers.size,0,'Names and typed input must bypass machine translation');
  const first=text('剩余说明'), second=text('剩余说明'), stale=text('另外说明');
  context.translate(first,first.nodeValue);context.translate(second,second.nodeValue);context.translate(stale,stale.nodeValue);
  pump();await settle();assert.equal(requests.length,1);
  assert.deepEqual(new URL(requests[0].url).searchParams.getAll('q'),['剩余说明','另外说明']);
  assert.equal(requests[0].options.credentials,'omit');
  stale.nodeValue='Nội dung mới';
  respond({ok:true,json:async()=>['Mô tả còn lại','Mô tả khác']});await settle();await settle();
  assert.equal(first.nodeValue,'Mô tả còn lại');assert.equal(second.nodeValue,'Mô tả còn lại');
  assert.equal(stale.nodeValue,'Nội dung mới');
  const cached=text('剩余说明');context.translate(cached,cached.nodeValue);
  assert.equal(cached.nodeValue,'Mô tả còn lại');assert.equal(requests.length,1);
  const failure=text('失败说明');context.translate(failure,failure.nodeValue);pump();await settle();
  respond({ok:false,status:503});await settle();await settle();
  assert.equal(failure.nodeValue,'失败说明');context.translate(failure,failure.nodeValue);
  assert.equal(timers.size,0,'Failed requests must wait before retrying');
  assert.equal(context.window.__iqiyiViAutoStatus().pending,0);
  console.log('Prepared-copy priority, batched fallback, deduplication, cache, stale DOM, private input and failure checks passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
