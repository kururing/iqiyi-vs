/* Run: node tests/check_web_audio_frame.cjs */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
let connect, audio, emitted = [];
class TestAudio extends EventTarget {
  constructor(){ super(); audio=this; this.paused=true;this.currentTime=0;this.readyState=0;this.seeking=false;this.error=null; }
  load(){this.readyState=1;this.dispatchEvent(new Event('loadedmetadata'));}
  play(){this.paused=false;this.readyState=4;this.dispatchEvent(new Event('playing'));return Promise.resolve();}
  pause(){this.paused=true;this.dispatchEvent(new Event('pause'));}
  removeAttribute(){this.src='';}
}
const parent = {};
const context = vm.createContext({Audio:TestAudio,URL,parent,Number,Error,location:{host:'a'.repeat(32)},
  window:{addEventListener:(event,fn)=>{if(event==='message')connect=fn}},setInterval(){}});
vm.runInContext(fs.readFileSync(path.join(__dirname,'../ext/audio-player.js'),'utf8'),context);
function port(){return {postMessage:m=>emitted.push(m),start(){},onmessage:null};}
let rejected = port();
connect({origin:'https://attacker.test',source:parent,data:{type:'iqiyi-audio-connect'},ports:[rejected]});
assert.equal(rejected.onmessage,null,'An unrelated origin cannot control the extension audio frame');
connect({origin:'https://www.iqiyi.com',source:{},data:{type:'iqiyi-audio-connect'},ports:[rejected]});
assert.equal(rejected.onmessage,null,'Even an allowed origin must be the parent frame');
const accepted=port();
connect({origin:'https://www.iqiyi.com',source:parent,data:{type:'iqiyi-audio-connect'},ports:[accepted]});
assert.equal(typeof accepted.onmessage,'function');
const token='a'.repeat(64), stream='b'.repeat(24);
const source=`http://127.0.0.1:18766/audio.mp4?tvid=1740399080201000&stream=${stream}&token=${token}`;
(async()=>{
  await accepted.onmessage({data:{type:'config',volume:.25,muted:false,rate:1.5}});
  await accepted.onmessage({data:{type:'seek',time:40}});
  await accepted.onmessage({data:{type:'load',src:source}});
  await accepted.onmessage({data:{type:'seek',time:40}});
  await accepted.onmessage({data:{type:'play',requestId:1}});
  assert.equal(audio.src,source);assert.equal(audio.currentTime,40);
  assert.equal(audio.volume,.25);assert.equal(audio.playbackRate,1.5);assert.equal(audio.paused,false);
  assert.ok(emitted.some(message=>message.requestId===1&&!message.error));
  await accepted.onmessage({data:{type:'pause'}});assert.equal(audio.paused,true);
  for(const url of ['https://attacker.test/audio.mp4',source.replace('/audio.mp4','/api/translation/start'),source.replace(token,'bad')]){
    emitted=[];await accepted.onmessage({data:{type:'load',src:url}});
    assert.equal(audio.src,source,'Invalid source addresses never reach the media element');
    assert.ok(emitted.some(message=>message.event==='error'));
  }
  const independent=`chrome-extension://${'a'.repeat(32)}/audio-stream.mp4?tvid=1740399080201000&stream=aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee`;
  await accepted.onmessage({data:{type:'load',src:independent}});
  assert.equal(audio.src,independent,'Accept only this extension worker stream');
  for(const invalid of [independent.replace('a'.repeat(32),'c'.repeat(32)),independent.replace('audio-stream.mp4','proxy-token.json')]){
    emitted=[];await accepted.onmessage({data:{type:'load',src:invalid}});
    assert.equal(audio.src,independent);assert.ok(emitted.some(message=>message.event==='error'));
  }
  console.log('Web audio frame checks passed: parent/origin checks, source restriction, play, seek, volume, rate and pause.');
})().catch(error=>{console.error(error);process.exitCode=1});
