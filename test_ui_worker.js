// Run: node test_ui_worker.js -- mocked extension worker, no browser actions.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
let listener,calls=0,pending;
const context={URL,URLSearchParams,AbortSignal,
 chrome:{runtime:{onMessage:{addListener(fn){listener=fn;}}}},
 fetch(url,options){calls++;assert.ok(url.startsWith('https://clients5.google.com/translate_a/t?'));assert.equal(options.credentials,'omit');return new Promise(resolve=>pending=resolve);}};
vm.runInNewContext(fs.readFileSync(__dirname+'/ext/ui-translate.js','utf8'),context);
const sender={tab:{id:1},origin:'https://player.iqiyi.com',url:'https://player.iqiyi.com/'};
function send(texts,from=sender){return new Promise(resolve=>listener({type:'iqiyi-vi-translate',texts},from,resolve));}
(async()=>{
 const first=send(['标签']),second=send(['标签']);assert.equal(calls,1);
 pending({ok:true,json:async()=>['Nhãn']});
 assert.deepEqual(JSON.parse(JSON.stringify(await first)),{translations:['Nhãn']});await second;
 await send(['标签']);assert.equal(calls,1,'Cache across pages and popup frames');
 const forged=await send(['标签'],{tab:{id:2},url:'https://iqiyi.com.evil.example/'});assert.ok(forged.error);
 const invalid=await send(Array(9).fill('标签'));assert.ok(invalid.error);assert.equal(calls,1);
 const blankFrame=await send(['标签'],{tab:{id:1},url:'about:blank',origin:'https://www.iqiyi.com'});assert.ok(blankFrame.translations);
 console.log('Worker batch sharing, caching, subdomain/blank-frame support and sender/input validation passed.');
})().catch(e=>{console.error(e);process.exitCode=1;});
