/* Run: node tests/check_iqcom_audio.cjs */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../ext/sub-hook.js'), 'utf8');
const start = source.indexOf('    function installIqcomAudio()');
const end = source.indexOf('    function installOfficialSubtitleGuard()', start);
let now = 100000, tick, tvid = '12345678', nativeMute = false, uiMute = false, volume = 35;
let pts = 10, playState = 'play', enabled = true, stream = 'stream1', speed = 100, messages = [], audios = [];
let tipsReady = true, notices = [], hiddenNotices = [];
let pollFailure = 0, playReject = null, playCalls = 0;
const gestures = {};
const tips = {tipList:()=>tipsReady?{}:null,showTip:(key,tip)=>notices.push({key,tip}),hideTip:key=>hiddenNotices.push(key)};
const controller = {
  store:{getProp:()=>1,setProp:(key,value)=>{if(key==='mute')uiMute=value}}, mute:()=>({get:()=>uiMute,set:v=>uiMute=v}),
  volume:()=>({get:()=>volume}),
  setMute(v){ nativeMute = uiMute = v; }, setVolume(v){ volume = v; }
};
const originalMute = controller.setMute, originalVolume = controller.setVolume;
const player = {innerData:{store:{getProp:k=>k==='ptsTime'?pts:false}}, totalTime:100,
  get curTime(){ return pts; },
  get videoPlayState(){ return playState; }};
const provider = {videoPlayerInstance:player,playerSupplementary:controller};
class NativeMenu {
  constructor(){this.renderMain=()=>['Existing settings'];}
  generateSettingOption(option,enabled,key){return {type:'native-option',option,enabled,key};}
  render(){return this.renderMain();}
  forceUpdate(){}
}
const originalMenuRender=NativeMenu.prototype.render;
function runtime(id) { return id==='1'?{provider}:id==='2'?{controller}:id==='4'?{M_:{getProp:()=>speed}}:id==='5'?{tips}:{NativeMenu}; }
runtime.m = {'1': function(){ /* videoPlayerInstance=void 0 */ },
  '2': function(){ /* Controller methods are inherited from a separate module. */ },
  '3': function(){ /* getAiScopeEntity renderMain secondPageContainer */ },
  '4': function(){ /* xplayerProgressTouch */ },
  '5': function(){ /* timersClose _getTip( showTip( */ }};
class Audio {
  constructor(){ this.listeners={}; this.paused=true; this.readyState=4; this.currentTime=0; audios.push(this); }
  addEventListener(k,f){ this.listeners[k]=f; }
  pause(){ this.paused=true; }
  play(){ playCalls++; if(playReject)return Promise.reject(playReject);this.paused=false; return Promise.resolve(); }
  load(){}
  removeAttribute(){}
}
const root = {Audio,document:{addEventListener:(name,fn)=>{gestures[name]=fn},removeEventListener:name=>{delete gestures[name]}},
  setInterval:f=>{tick=f;return 1},clearInterval(){},addEventListener(){}};
const context = vm.createContext({root,iqPlayer:false,officialRuntimeRequire:runtime,
  officialNativeControl:{store:{getProp:()=>speed}},
  currentSubtitleTvid:()=>tvid,post:(_,data)=>{messages.push(data.message);return Promise.resolve()},
  SIDE:'http://127.0.0.1:18766',ensureToken:()=>Promise.resolve('player-token'),AbortSignal,
  localFetch:(_url,options)=>{if(pollFailure&&_url.includes('/api/audio-state'))return pollFailure===1?Promise.reject(Error('temporary timeout')):Promise.resolve({ok:false,status:pollFailure});if(options.method==='POST')enabled=JSON.parse(options.body).enabled;return Promise.resolve({ok:true,json:()=>Promise.resolve({enabled,available:enabled,
    stream,shiftSeconds:2,duration:100,episode:1})})}, Date:{now:()=>now}});
vm.runInContext(source.slice(start,end),context);
const flush = async()=>{for(let i=0;i<5;i++)await new Promise(resolve=>setImmediate(resolve))};
(async()=>{
  context.installIqcomAudio(); tick(); await flush();
  assert.equal(audios.length,1);
  assert.equal(root.__iqiyiAudioEngine.status().sourceReady,true,'Find the mounted controller even when its factory has no volume method bodies');
  assert.equal(nativeMute,false,'Keep the original soundtrack until playback succeeds');
  assert.equal(notices.at(-1).tip.desc[1].text,'Đã chọn tiếng Việt iq.com.');
  assert.equal(notices.at(-1).tip.attr.group,'default','Reuse the subtitle notification group');
  assert.equal(notices.at(-1).tip.attr.close_time,4,'Use the player notification timeout');
  tick(); await flush();
  assert.equal(audios[0].currentTime,8,'Apply the edition offset automatically');
  assert.equal(nativeMute,true);
  assert.match(notices.at(-1).tip.desc[1].text,/Đang dùng âm thanh Việt/);
  const stableNotices=notices.length;tick();await flush();tick();await flush();
  assert.equal(notices.length,stableNotices,'Playback polling never repeats the same notice');
  const initialSeeks=root.__iqiyiAudioEngine.status().seeks;
  pts=10.8;tick();await flush();
  assert.equal(audios[0].currentTime,8,'One noisy native clock sample must not seek/restart AAC');
  pts=10;tick();await flush();
  assert.equal(root.__iqiyiAudioEngine.status().seeks,initialSeeks);
  pts=10.8;tick();await flush();tick();await flush();tick();await flush();
  assert.equal(audios[0].currentTime,8.8,'Correct a sustained drift after three samples');
  audios[0].seeking=true;pts=30;audios[0].currentTime=3;tick();await flush();
  assert.equal(audios[0].currentTime,3,'Never reset an asynchronous seek while it is still in progress');
  audios[0].seeking=false;pts=10;audios[0].currentTime=8;tick();await flush();
  speed=150; tick(); await flush(); assert.equal(audios[0].playbackRate,1.5);
  speed=100;
  assert.equal(uiMute,false,'Keep the user mute control independent of the native soundtrack');
  controller.store.setProp('mute',true);
  assert.equal(uiMute,false,'Ignore asynchronous IPC echoes of the physical mute');
  assert.equal(audios[0].muted,false);
  controller.setVolume(20); controller.setMute(true);
  assert.equal(nativeMute,true); assert.equal(audios[0].volume,.2); assert.equal(audios[0].muted,true);
  controller.setMute(false); assert.equal(nativeMute,true); assert.equal(audios[0].muted,false);
  playState='pause'; tick(); await flush();
  assert.equal(audios[0].paused,true); assert.equal(nativeMute,false);
  pts=40; playState='play'; now+=300; tick(); await flush();
  assert.equal(audios[0].currentTime,38,'Seek the external soundtrack with native playback');
  assert.equal(nativeMute,true);
  audios[0].readyState=2; audios[0].listeners.waiting();
  assert.equal(nativeMute,false,'Restore original sound while buffering');
  assert.match(notices.at(-1).tip.desc[1].text,/Đang đệm/);
  const bufferingNotices=notices.length;audios[0].listeners.waiting();
  assert.equal(notices.length,bufferingNotices,'Repeated buffering events show one notice');
  audios[0].readyState=4; tick(); await flush(); assert.equal(nativeMute,true);
  assert.match(root.__iqiyiAudioEngine.status().message,/Đang dùng âm thanh Việt/,'Keep the menu status current after buffering recovers');
  assert.equal(notices.length,bufferingNotices,'Recovery does not repeat the playing notice');
  for(let i=0;i<12;i++){
    audios[0].readyState=2;audios[0].listeners.waiting();
    audios[0].readyState=4;pts+=.2;now+=200;tick();await flush();
  }
  assert.equal(notices.length,bufferingNotices,'Buffering/playback oscillation never floods native notifications');
  audios[0].listeners.error(); await flush(); assert.equal(nativeMute,false);
  assert.equal(controller.setMute,originalMute); assert.equal(controller.setVolume,originalVolume);
  now+=2500; tick(); await flush(); assert.equal(audios.length,1,'Do not loop on a failed stream');
  tvid='87654321'; stream='stream2'; pts=5; now+=2500; tick(); await flush(); tick(); await flush();
  assert.equal(audios.length,2); assert.equal(audios[0].paused,true,'Never leave the previous episode audible');
  assert.match(notices.at(-1).tip.desc[1].text,/Đang dùng âm thanh Việt/,'A new episode can show its playback notice');
  const menu=new NativeMenu(), tree=menu.render();
  const controls=tree[1];
  assert.equal(controls.type,'native-option','Use the existing player option renderer');
  assert.equal(controls.option.title,'Âm thanh');
  assert.equal(controls.option.optionValue(),'Tiếng Việt iq.com');
  assert.equal(controls.option.data().map(t=>t.title).join('|'),'Tiếng gốc|Tiếng Việt iq.com');
  controls.option.secondPage.onItemClick({id:'original'}); await flush();
  assert.equal(enabled,false,'Save the player setting immediately');
  assert.equal(notices.at(-1).tip.desc[1].text,'Đã chuyển sang tiếng gốc.');
  now+=2500; tick(); await flush();
  assert.equal(nativeMute,false); assert.equal(audios[1].paused,true);
  assert.equal(controller.setMute,originalMute);
  controls.option.secondPage.onItemClick({id:'vietnamese'});await flush();
  now+=2500;pts+=.2;tick();await flush();pts+=.2;tick();await flush();
  assert.match(notices.at(-1).tip.desc[1].text,/Đang dùng âm thanh Việt/,'Explicitly selecting Vietnamese again resets notifications');
  root.__iqiyiAudioEngine.dispose();
  assert.equal(hiddenNotices.at(-1),'iqiyi_vi_audio_status','An upgrade removes only its own audio notice');
  assert.equal(NativeMenu.prototype.render,originalMenuRender,'Restore native menu hooks on upgrade');
  delete provider.playerSupplementary;
  runtime.m['2']=function(){ /* setMute( volume(){ */ };
  enabled=true;stream='legacy-stream';now+=6000;tipsReady=false;
  context.installIqcomAudio();tick();await flush();
  assert.equal(root.__iqiyiAudioEngine.status().sourceReady,true,'Keep support for the older exported controller');
  const deferredCount=notices.length;
  tipsReady=true;tick();await flush();
  assert.ok(notices.length>deferredCount,'Show pending status once the native notification controller mounts');
  const playingAudio=audios.at(-1), count=audios.length;
  pollFailure=1;now+=2500;pts+=.2;playingAudio.currentTime=pts-2;tick();await flush();
  assert.equal(root.__iqiyiAudioEngine.status().sourceReady,true,'Keep buffered audio through a transient status timeout');
  assert.equal(audios.length,count);
  pollFailure=403;now+=2500;pts+=.2;playingAudio.currentTime=pts-2;tick();await flush();
  assert.equal(root.__iqiyiAudioEngine.status().sourceReady,false,'Stop immediately when playback authorization is revoked');
  assert.equal(nativeMute,false);
  pollFailure=0;now+=2500;pts+=.2;tick();await flush();tick();await flush();
  let recovering=audios.at(-1);
  recovering.error={code:2};recovering.listeners.error();await flush();
  assert.equal(nativeMute,false);
  const beforeReconnect=audios.length;
  now+=1000;pts+=.2;tick();await flush();
  assert.equal(audios.length,beforeReconnect,'Wait before retrying a network failure');
  now+=1500;pts+=.2;tick();await flush();
  assert.equal(audios.length,beforeReconnect+1,'Reconnect a transient media network failure automatically');
  assert.equal(root.__iqiyiAudioEngine.status().reconnects,1);
  playReject=Object.assign(Error('gesture required'),{name:'NotAllowedError'});
  tick();await flush();
  assert.equal(root.__iqiyiAudioEngine.status().autoplayBlocked,true);
  const blockedCalls=playCalls;tick();await flush();tick();await flush();
  assert.equal(playCalls,blockedCalls,'Do not hammer a denied autoplay permission every 200 ms');
  playReject=null;gestures.keydown();await flush();
  assert.equal(root.__iqiyiAudioEngine.status().autoplayBlocked,false,'Keyboard activation can resume the soundtrack');
  root.__iqiyiAudioEngine.dispose();
  console.log('Audio checks passed: sync, seek, pause/resume, volume, mute, buffering, errors, episode changes, disable and native player notices without repeated polling.');
})().catch(error=>{console.error(error);process.exitCode=1});
