// Run: node test_ui_coverage.js -- no browser or network required.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
let observed=[],timers=[],requests=0;
function element(tag='SPAN',text='',attrs={}) {
 const el={nodeType:1,tagName:tag,className:'',id:'',attrs:{...attrs},style:{},isConnected:true,
   childNodes:[],childElementCount:0,clientHeight:0,clientWidth:0,
   getAttribute(name){return this.attrs[name]??null;},
   setAttribute(name,value){this.attrs[name]=value;},
   closest(selector){return selector.includes('contenteditable')&&this.isContentEditable?this:null;},
   append(child){this.childNodes.push(child);this.firstChild=this.childNodes[0];child.parentElement=this;this.childElementCount=this.childNodes.filter(n=>n.nodeType===1).length;return child;}};
 Object.defineProperty(el,'textContent',{get:()=>el.childNodes.map(n=>n.nodeType===3?n.nodeValue:n.textContent).join('')});
 if(text)el.append({nodeType:3,nodeValue:text,isConnected:true});
 return el;
}
const ctx={window:{fetch:true},
 fetch(){requests++;throw new Error('Automatic translation requests are disabled');},
 document:{getElementById:()=>null},location:{pathname:'/',href:'https://www.iqiyi.com/'},localStorage:{length:0},
 AbortController,Date,requestAnimationFrame:()=>1,
 MutationObserver:class {constructor(fn){this.fn=fn;}observe(root,options){observed.push({root,options,callback:this.fn});}disconnect(){}},
 setTimeout(fn,ms){timers.push({fn,ms});return timers.length;},clearTimeout(){}};
let src=fs.readFileSync(__dirname+'/ui-engine.js','utf8');
src=src.slice(0,src.indexOf('  function run()'))+'function run(){};globalThis.walk=walk;globalThis.observeRoot=observeRoot;})();';vm.runInNewContext(src,ctx);
const shadowText=element('BUTTON','关闭');const shadow={nodeType:11,childNodes:[shadowText]};
const host=element('CUSTOM-PLAYER');host.shadowRoot=shadow;ctx.walk(host);
assert.equal(shadowText.textContent,'Đóng');
ctx.walk(host);assert.equal(observed.length,1,'Observe shadow roots once');
assert.ok(observed[0].options.attributeFilter.includes('title'),'Observe tooltip changes');
const mutationRoot={nodeType:9,childNodes:[]};ctx.observeRoot(mutationRoot);
const mutationObserver=observed.find(entry=>entry.root===mutationRoot).callback;
const skipCountdown=element('SPAN','7秒后可跳过广告');ctx.walk(skipCountdown);
for(const seconds of [6,5,4,3,2,1,0]) {
 const text=skipCountdown.firstChild;text.nodeValue=seconds+'秒后可跳过广告';
 mutationObserver([{type:'characterData',target:text}]);
 assert.equal(text.nodeValue,'Có thể bỏ qua quảng cáo sau '+seconds+' giây','Translate each ad countdown update before the next paint');
}
const continueCountdown=element('SPAN','5s后可继续看正片');ctx.walk(continueCountdown);
for(const seconds of [4,3,2,1,0]) {
 const text=continueCountdown.firstChild;text.nodeValue=seconds+'秒后可继续看正片';
 mutationObserver([{type:'characterData',target:text}]);
 assert.equal(text.nodeValue,'Sau '+seconds+' giây có thể xem tiếp phim','Translate the alternate ad countdown on each update');
}
const playerToast=element('SPAN','已切换主字幕为 Tiếng Việt iq.com');ctx.walk(playerToast);
playerToast.firstChild.nodeValue='已切换主字幕为 Tiếng Việt';
mutationObserver([{type:'characterData',target:playerToast.firstChild}]);
assert.equal(playerToast.textContent,'Đã chuyển phụ đề chính sang Tiếng Việt','Translate updated player notifications immediately');
const insertedMenu=element('SPAN','关闭此广告');
mutationObserver([{type:'childList',addedNodes:[insertedMenu]}]);
assert.equal(insertedMenu.textContent,'Tắt quảng cáo này','Translate newly inserted player menu copy immediately');
const updatedTooltip=element('BUTTON','', {title:'播放设置'});
mutationObserver([{type:'attributes',target:updatedTooltip}]);
assert.equal(updatedTooltip.attrs.title,'Cài đặt phát','Translate updated player tooltips immediately');
const frameText=element('BUTTON','下一集');const frame=element('IFRAME');frame.contentDocument={nodeType:9,documentElement:frameText,childNodes:[frameText]};
ctx.walk(frame);assert.equal(frameText.textContent,'Tập tiếp');
const blockedFrame=element('IFRAME');Object.defineProperty(blockedFrame,'contentDocument',{get(){throw Error('Cross origin');}});ctx.walk(blockedFrame);
const parent=element('DIV','',{'data-albumid':'123456789012345'});const heading=parent.append(element('H3','播放设置'));
ctx.walk(heading);assert.equal(heading.textContent,'Cài đặt phát','A UI heading inside a film card is not the film name');
const input=element('INPUT','', {placeholder:'未知提示',value:'用户输入'});input.value='用户输入';input.type='text';
ctx.walk(input);assert.equal(input.attrs.value,'用户输入');assert.equal(input.value,'用户输入');
const textarea=element('TEXTAREA','用户草稿',{placeholder:'未知提示'});ctx.walk(textarea);assert.equal(textarea.textContent,'用户草稿');
assert.equal(input.attrs.placeholder,'未知提示');assert.equal(textarea.attrs.placeholder,'未知提示');
const missing=element('SPAN','未收录的中文提示');ctx.walk(missing);
assert.equal(missing.textContent,'未收录的中文提示','Unknown UI copy remains stable when no manual translation exists');
const editable=element('DIV','关闭');editable.isContentEditable=true;ctx.walk(editable);assert.equal(editable.textContent,'关闭');
const subtitle=element('DIV','下一集');subtitle.id='pcaSubtitleContainer';ctx.walk(subtitle);assert.equal(subtitle.textContent,'下一集');
assert.equal(requests,0,'Missing UI translations must not trigger a network request');
assert.equal(timers.length,0,'Missing UI translations must not queue a fallback request');
assert.equal(ctx.window.__iqiyiViAutoStatus,undefined,"No UI translation status shim remains");
console.log('App/web coverage: prepared copy, source-language fallback, shadow roots, frames, popup attributes, typed values and subtitle exclusions passed.');
