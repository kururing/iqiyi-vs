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
  const context=vm.createContext({document,location:{hostname:host},window:{__iqiyiViToken:token},AbortSignal,
    fetch:async(url,options)=>{calls.push({url,options});return respond(url,options)}});
  vm.runInContext(code,context);
  return {context,children,calls,label,get button(){return button},setResponse:fn=>respond=fn};
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
  assert.equal(web.button,undefined,'A public website cannot open the local manager window');
  console.log('Manager shortcut checks passed: native-only placement, cached token, fallback token, duplicate clicks and failure recovery.');
})().catch(error=>{console.error(error);process.exitCode=1});
