// Run: node test_ui_transports.js
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const settle=()=>new Promise(resolve=>setImmediate(resolve));
let source=fs.readFileSync(__dirname+'/ui-engine.js','utf8');
source=source.slice(0,source.indexOf('  function run()'))+'globalThis.translate=autoTranslate;})();';
function runtime(window,fetch) {
 const timers=new Map();let id=0;
 const ctx={window:{fetch:true,...window},fetch,AbortController,Date,document:{getElementById:()=>null},
 location:{pathname:'/',href:'https://localwebapp.iqiyi.com/index.html'},localStorage:{length:0},
 setTimeout(fn,ms){timers.set(++id,{fn,ms});return id;},clearTimeout(key){timers.delete(key);}};
 vm.runInNewContext(source,ctx);
 return {ctx,pump(){for(const [key,timer]of timers)if(timer.ms<1000){timers.delete(key);timer.fn();return true;}return false;}};
}
function text(value){return {nodeType:3,nodeValue:value,isConnected:true,parentElement:{nodeType:1,tagName:'SPAN',getAttribute:()=>null,closest:()=>null}};}
(async()=>{
 let batches=[];
 const bridge=runtime({__iqiyiViTranslate:async texts=>{batches.push(texts);return texts.map(()=> 'Mô tả đầy đủ');}},()=>assert.fail('Worker bridge must handle web requests'));
 const paragraph=text('长篇剧情介绍。'.repeat(100));bridge.ctx.translate(paragraph,paragraph.nodeValue);
 for(let i=0;i<10;i++){bridge.pump();await settle();await settle();}
 assert.ok(batches.flat().every(value=>value.length<=500));assert.ok(batches.flat().length>1);
 assert.equal(/[一-龥]/.test(paragraph.nodeValue),false,'Long descriptions must no longer be skipped');
 const cachedParagraph=text('长篇剧情介绍。'.repeat(100));bridge.ctx.translate(cachedParagraph,cachedParagraph.nodeValue);
 assert.equal(/[一-龥]/.test(cachedParagraph.nodeValue),false,'Cached long descriptions must also commit');
 let urls=[];
 const native=runtime({__iqiyiViToken:'test-token'},async(url,options)=>{
   urls.push(url);assert.equal(options.headers['X-Iqiyi-Token'],'test-token');
   return {ok:true,json:async()=>({translations:['Nhãn app']})};
 });
 const label=text('未知应用标签');native.ctx.translate(label,label.nodeValue);native.pump();await settle();await settle();
 assert.equal(label.nodeValue,'Nhãn app');assert.deepEqual(urls,['http://127.0.0.1:18766/api/ui-translate']);
 const fallback=runtime({__iqiyiViToken:'test-token'},async(url,options)=>{
   if(url.startsWith('http://127.0.0.1'))return {ok:false,status:404};
   assert.equal(options.headers,undefined,'Never forward the local API token to Google');
   return {ok:true,json:async()=>['Nhãn dự phòng']};
 });
 const legacy=text('未知旧应用标签');fallback.ctx.translate(legacy,legacy.nodeValue);fallback.pump();await settle();await settle();
 assert.equal(legacy.nodeValue,'Nhãn dự phòng');
 console.log('Web worker bridge, long descriptions, authenticated app transport and legacy-server fallback passed.');
})().catch(e=>{console.error(e);process.exitCode=1;});
