// Run: node test_ui_coverage.js -- no browser or network required.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
let observed=[],timers=[],calls=[];
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
const ctx={window:{fetch:true,__iqiyiViTranslate:async texts=>{calls.push(texts);return texts.map(()=> 'Gợi ý còn thiếu');}},
 document:{getElementById:()=>null},location:{pathname:'/',href:'https://www.iqiyi.com/'},localStorage:{length:0},
 AbortController,Date,requestAnimationFrame:()=>1,
 MutationObserver:class {constructor(fn){this.fn=fn;}observe(root,options){observed.push({root,options});}disconnect(){}},
 setTimeout(fn,ms){timers.push({fn,ms});return timers.length;},clearTimeout(){}};
let src=fs.readFileSync(__dirname+'/ui-engine.js','utf8');
src=src.slice(0,src.indexOf('  function run()'))+'globalThis.walk=walk;})();';vm.runInNewContext(src,ctx);
const shadowText=element('BUTTON','关闭');const shadow={nodeType:11,childNodes:[shadowText]};
const host=element('CUSTOM-PLAYER');host.shadowRoot=shadow;ctx.walk(host);
assert.equal(shadowText.textContent,'Đóng');
ctx.walk(host);assert.equal(observed.length,1,'Observe shadow roots once');
assert.ok(observed[0].options.attributeFilter.includes('title'),'Observe tooltip changes');
const frameText=element('BUTTON','下一集');const frame=element('IFRAME');frame.contentDocument={nodeType:9,documentElement:frameText,childNodes:[frameText]};
ctx.walk(frame);assert.equal(frameText.textContent,'Tập tiếp');
const blockedFrame=element('IFRAME');Object.defineProperty(blockedFrame,'contentDocument',{get(){throw Error('Cross origin');}});ctx.walk(blockedFrame);
const parent=element('DIV','',{'data-albumid':'123456789012345'});const heading=parent.append(element('H3','播放设置'));
ctx.walk(heading);assert.equal(heading.textContent,'Cài đặt phát','A UI heading inside a film card is not the film name');
const input=element('INPUT','', {placeholder:'未知提示',value:'用户输入'});input.value='用户输入';input.type='text';
ctx.walk(input);assert.equal(input.attrs.value,'用户输入');assert.equal(input.value,'用户输入');
const textarea=element('TEXTAREA','用户草稿',{placeholder:'未知提示'});ctx.walk(textarea);assert.equal(textarea.textContent,'用户草稿');
const editable=element('DIV','关闭');editable.isContentEditable=true;ctx.walk(editable);assert.equal(editable.textContent,'关闭');
const subtitle=element('DIV','下一集');subtitle.id='pcaSubtitleContainer';ctx.walk(subtitle);assert.equal(subtitle.textContent,'下一集');
(async()=>{
 for(const timer of timers.splice(0))if(timer.ms<1000)timer.fn();
 await new Promise(resolve=>setImmediate(resolve));await new Promise(resolve=>setImmediate(resolve));
 assert.equal(input.attrs.placeholder,'Gợi ý còn thiếu');assert.equal(textarea.attrs.placeholder,'Gợi ý còn thiếu');
 assert.equal(calls.length,1,'Duplicate placeholders across dialogs share a request');
 console.log('App/web coverage: shadow roots, frames, card headings, popup attributes, textareas, typed values and subtitle exclusions passed.');
})().catch(e=>{console.error(e);process.exitCode=1;});
