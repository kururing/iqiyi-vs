/* Run: node tests/check_manager_shortcut.cjs */
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(require('node:path').join(__dirname,'../ext/content.js'),'utf8');
const code=source.slice(source.indexOf('  function installManagerShortcut()'),source.indexOf('  function run()'));
function fixture(host='localwebapp.iqiyi.com',token='player-token'){
  const label={textContent:'Quản lý phụ đề'},coin={name:'coin'},children=[coin],calls=[];
  let button,respond=async()=>({ok:true,json:async()=>({ok:true,token:'fallback-token'})});
  const document={
    getElementById:()=>button?.parentElement?button:null,
    querySelector:()=>tools,
    createElement:()=>button={disabled:false,attrs:{},setAttribute(k,v){this.attrs[k]=v},querySelector:()=>label}
  };
  const tools={querySelector:()=>coin,firstChild:coin,insertBefore(node,before){children.splice(children.indexOf(before),0,node);node.parentElement=this}};
  const opened=[];
  const context=vm.createContext({document,location:{hostname:host},window:{__iqiyiViToken:token,open:(...args)=>opened.push(args)},AbortSignal,
    fetch:async(url,options)=>{calls.push({url,options});return respond(url,options)}});
  vm.runInContext(code,context);
  return {context,children,calls,opened,label,get button(){return button},setResponse:fn=>respond=fn};
}
(async()=>{
  const native=fixture();native.context.installManagerShortcut();native.context.installManagerShortcut();
  assert.equal(native.children.length,2,'Keep one shortcut beside the existing tools');
  assert.equal(native.children[0],native.button,'Place it before the check-in icon');
  assert.equal(native.button.attrs['aria-label'],'Quản lý phụ đề');
  await native.button.onclick();
  assert.equal(native.calls.length,1,'Use the native player token; native requests may omit Origin');
  assert.ok(native.calls[0].url.endsWith('/api/open-manager'));
  assert.equal(native.calls[0].options.headers['X-Iqiyi-Token'],'player-token');
  assert.equal(native.button.title,'Đã mở quản lý phụ đề');
  let finish;
  native.setResponse(()=>new Promise(resolve=>finish=resolve));
  const pending=native.button.onclick();await native.button.onclick();
  assert.equal(native.calls.length,2,'Ignore duplicate clicks while opening');
  finish({ok:false,json:async()=>({error:'Không mở được cửa sổ'})});await pending;
  assert.equal(native.button.disabled,false);assert.equal(native.button.title,'Không mở được cửa sổ');
  const fallback=fixture('localwebapp.iqiyi.com','');fallback.context.installManagerShortcut();
  await fallback.button.onclick();assert.equal(fallback.calls.length,2);
  assert.equal(fallback.calls[1].options.headers['X-Iqiyi-Token'],'fallback-token');
  const web=fixture('www.iqiyi.com');web.context.installManagerShortcut();
  await web.button.onclick();
  assert.deepEqual(web.opened,[],'The website never opens a browser tab');
  assert.equal(web.calls.length,1);
  assert.ok(web.calls[0].url.endsWith('/api/open-manager'));
  assert.equal(web.button.title,'Đã mở quản lý phụ đề');
  const unrelated=fixture('evil.test');unrelated.context.installManagerShortcut();
  assert.equal(unrelated.button,undefined);
  await checkWorker();
  console.log('Manager shortcut checks passed: web/native open the app without new tabs, limited worker route, sender validation, tokens and failure recovery.');
})().catch(error=>{console.error(error);process.exitCode=1});

async function checkWorker(){
  const listeners=[],calls=[];
  const ctx=vm.createContext({URL,AbortController,setTimeout,clearTimeout,crypto:require('node:crypto').webcrypto,
    chrome:{runtime:{id:'test-extension',getURL:name=>'chrome-extension://test-extension/'+name,onMessage:{addListener:fn=>listeners.push(fn)}}},
    fetch:async(url,options)=>{
      calls.push({url,options});
      if(url==='chrome-extension://test-extension/proxy-token.json')
        return {ok:true,json:async()=>({token:'proxy-only',sessionToken:'session-only',playerToken:'player-only'})};
      assert.equal(url,'http://127.0.0.1:18766/api/open-manager');
      assert.equal(options.method,'POST');
      assert.equal(options.headers['X-Iqiyi-Token'],'player-only');
      return {status:200,headers:{get:()=> 'application/json'},text:async()=>'{"ok":true}'};
    }});
  vm.runInContext(fs.readFileSync(require('node:path').join(__dirname,'../ext/local-api-worker.js'),'utf8'),ctx);
  const message={type:'iqiyi-local-api',path:'/api/open-manager',method:'POST',body:'{}'};
  for(const sender of [{id:'other',url:'https://www.iqiyi.com/'},{id:'test-extension',url:'https://evil.test/'},
    {id:'test-extension',url:'https://www.iqiyi.com.evil.test/'}]){
    assert.equal(listeners[0](message,sender,()=>{throw Error('Untrusted sender received a reply')}),undefined);
  }
  assert.equal(calls.length,0);
  const result=await new Promise(resolve=>listeners[0](message,{id:'test-extension',url:'https://www.iqiyi.com/',tab:{id:1},frameId:0},resolve));
  assert.deepEqual(JSON.parse(result.body),{ok:true});
  assert.equal(calls.length,2);
  for(const path of ['/api/translation/cancel','/api/app-localization','/api/iqcom-login'])
    await assert.rejects(ctx.localPlayerRequest({path,method:'POST',body:'{}'}),/không được phép/);
  assert.equal(calls.length,2,'Opening the app must not expose its other management routes');
}
