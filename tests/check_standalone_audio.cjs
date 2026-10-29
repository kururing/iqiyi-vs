/* Run: node tests/check_standalone_audio.cjs */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const zlib = require('node:zlib');
const workerSource = fs.readFileSync(require('node:path').join(__dirname,'../ext/audio-worker.js'),'utf8');
const id='a'.repeat(32), tvid='12345678', album='22222222', globalTvid='33333333';
const init=Buffer.from('\0\0\0\x18ftypisom\0\0\0\0moovmp4a'), parts=[zlib.gzipSync(init),Buffer.from('12345678'),Buffer.from('abcdefgh')];
const track={lid:161,cf:'aac',ff:'amp4',duration:100,fs:parts.map((raw,i)=>({l:`/v0/test/${i}.amp4?signature=private`,b:raw.length}))};
const dash={tvid:globalTvid,aid:album,dd:'https://data.video.iqiyi.com/videos',program:{audio:[track]}};
const original={qipuId:'11111111',name:'测试剧',chnId:2,publishTime:'20230101',total:40,audioInfoList:[{id:1}]};
const vietnamese={...original,qipuId:album,name:'测试剧 越南语版',audioInfoList:[{id:161}],playLocSuffix:'test-episode',defaultTvId:globalTvid};
const page={props:{initialState:{play:{cachePlayList:{1:[{tvId:globalTvid,albumId:album,order:1,contentType:1,playLocSuffix:'test-episode'}]}}},
  initialProps:{pageProps:{prePlayerData:{dash:{data:dash}}}}}};
function fixture(storage={}) {
  let fetches=[], handlers=[], closed=[], upstreamMode='valid';
  const requestListeners=new Set();
  const json=value=>new Response(JSON.stringify(value),{headers:{'Content-Type':'application/json'}});
  const context=vm.createContext({URL,Response,Request,ReadableStream,Blob,DecompressionStream,TextDecoder,Uint8Array,AbortController,AbortSignal,
    crypto:require('node:crypto').webcrypto,setTimeout,clearTimeout,
    cleanPublicText:v=>String(v||'').trim(),
    publicJson:async()=>({data:{tvId:tvid,albumId:'11111111',order:1,durationSec:102}}),
    publicMovieTitle:async()=>({globalAlbumId:'11111111'}),
    catalogAlbum:async identifier=>identifier===album?vietnamese:original,
    searchCatalog:async()=>({data:{epg:[{name:vietnamese.name,qipuId:album,type:1}]}}),
    chrome:{runtime:{id,getURL:path=>'chrome-extension://'+id+'/'+path.replace(/^\//,'')},
      storage:{session:{get:async key=>({[key]:storage[key]}),set:async values=>Object.assign(storage,structuredClone(values))},
        local:{get:async key=>({[key]:storage[key]}),set:async values=>Object.assign(storage,values)}},
      cookies:{onChanged:{addListener(){}}},declarativeNetRequest:{updateSessionRules:async()=>{}},
      webRequest:{onBeforeRequest:{addListener:fn=>requestListeners.add(fn),removeListener:fn=>requestListeners.delete(fn)}},
      scripting:{executeScript:async()=>[{result:dash}]},
      tabs:{create:async()=>({id:7}),update:async(tabId,settings)=>{
        if(settings.url&&upstreamMode!=='page-metadata')queueMicrotask(()=>requestListeners.forEach(fn=>fn({tabId,url:`https://cache.video.iq.com/dash?tvid=${globalTvid}&signature=private`})));
      },remove:async tabId=>closed.push(tabId)}},
    self:{addEventListener:(type,fn)=>handlers.push({type,fn})},
    fetch:async(input,options)=>{
      const url=new URL(input);fetches.push(url.href);
      assert.equal(url.protocol,'https:','Audio never reads config or calls localhost');
      if(url.host==='www.iq.com'){
        assert.equal(options.credentials,'include','Use only the iq.com origin for browser cookies');
        const response=new Response('<script id="__NEXT_DATA__" type="application/json">'+JSON.stringify(page)+'</script>');
        Object.defineProperty(response,'url',{value:url.href});return response;
      }
      assert.equal(options.credentials,'omit');
      if(url.pathname==='/dash')return json({data:dash});
      if(url.host==='data.video.iqiyi.com')return json({l:'https://v-test.71edge.com:8402/'+url.pathname.split('/').at(-1)});
      const index=Number(url.pathname.match(/\/(\d+)\.amp4$/)?.[1]);
      assert.ok(Number.isInteger(index));
      if(index===0)return new Response(parts[0]);
      const range=/^bytes=(\d+)-(\d+)$/.exec(options.headers.Range), low=+range[1],high=+range[2];
      return new Response(parts[index].subarray(low,high+1),{status:upstreamMode==='ignored-range'?200:206,
        headers:{'Content-Range':`bytes ${low}-${high}/${parts[index].length+(upstreamMode==='wrong-length'?1:0)}`}});
    }});
  vm.runInContext(workerSource,context);
  const send=async(path,body)=>JSON.parse((await context.browserAudioRequest(new URL('http://127.0.0.1:18766'+path),{body:body===undefined?undefined:JSON.stringify(body)})).body);
  const evaluate=code=>vm.runInContext(code,context);
  return {context,fetches,storage,send,evaluate,closed,requestListeners,setMode:mode=>upstreamMode=mode};
}
(async()=>{
  const f=fixture();
  assert.equal((await f.send('/api/audio-state?tvid='+tvid)).enabled,false);assert.equal(f.fetches.length,0);
  await assert.rejects(f.send('/api/audio-settings',{enabled:1}),/không hợp lệ/);
  await f.send('/api/audio-settings',{enabled:true});
  assert.equal((await f.send('/api/audio-state?tvid='+tvid)).loading,true);
  await f.evaluate(`audioJobs.get('${tvid}')`);
  const state=await f.send('/api/audio-state?tvid='+tvid);
  assert.equal(state.available,true);assert.equal(state.shiftSeconds,2);assert.equal(state.episode,1);
  f.evaluate(`audioSources.get('${tvid}').expires = 0`);
  assert.equal((await f.send('/api/audio-state?tvid='+tvid)).stream,state.stream,'Refresh keeps the playing stream');
  await f.evaluate(`audioJobs.get('${tvid}')`);
  assert.equal((await f.send('/api/audio-state?tvid='+tvid)).stream,state.stream,'A completed refresh keeps the playing stream');
  assert.ok(!JSON.stringify(state).includes('signature'),'Signed metadata never reaches the player page');
  const media=`chrome-extension://${id}/audio-stream.mp4?tvid=${tvid}&stream=${state.stream}`,expected=Buffer.concat([init,...parts.slice(1)]);
  for(const [low,high] of [[0,expected.length-1],[init.length-2,init.length+10],[expected.length-4,expected.length-1]]){
    const response=await f.context.browserAudioStream(new Request(media,{headers:{Range:`bytes=${low}-${high}`}}));
    assert.equal(response.status,206);
    assert.equal(response.headers.get('Content-Range'),`bytes ${low}-${high}/${expected.length}`);
    assert.deepEqual(Buffer.from(await response.arrayBuffer()),expected.subarray(low,high+1));
  }
  const head=await f.context.browserAudioStream(new Request(media,{method:'HEAD'}));
  assert.equal(head.headers.get('Content-Length'),String(expected.length));assert.equal(await head.text(),'');
  assert.equal((await f.context.browserAudioStream(new Request(media,{headers:{Range:'bytes=9999-'}}))).status,416);
  assert.equal((await f.context.browserAudioStream(new Request(media.replace(state.stream,'wrong')))).status,403);
  for(const invalid of ['https://127.0.0.1/x','https://data.video.iqiyi.com:8402/x','https://u:p@data.video.iqiyi.com/x','https://iq.com.attacker.test/x'])assert.throws(()=>f.context.audioMediaUrl(invalid));
  for(const mode of ['ignored-range','wrong-length']){
    f.setMode(mode);
    const response=await f.context.browserAudioStream(new Request(media,{headers:{Range:`bytes=${init.length+1}-${init.length+3}`}}));
    await assert.rejects(response.arrayBuffer(),/sai vùng/);
  }
  const restarted=fixture(f.storage);
  assert.equal((await restarted.send('/api/audio-state?tvid='+tvid)).stream,state.stream,'Private session metadata survives worker restarts');
  const response=await restarted.context.browserAudioStream(new Request(media,{headers:{Range:'bytes=-4'}}));
  assert.equal(await response.text(),'efgh');
  const captured=await restarted.context.audioBrowserDash('https://www.iq.com/play/test',globalTvid,album,AbortSignal.timeout(1000));
  assert.equal(captured.tvid,globalTvid);assert.deepEqual(restarted.closed,[7]);assert.equal(restarted.requestListeners.size,0);
  restarted.setMode('page-metadata');
  const pageMetadata=await restarted.context.audioBrowserDash('https://www.iq.com/play/test',globalTvid,album,AbortSignal.timeout(2000));
  assert.equal(pageMetadata.tvid,globalTvid,'Read the account-bound page metadata even when no second DASH request is made');
  assert.deepEqual(restarted.closed,[7,7]);assert.equal(restarted.requestListeners.size,0);
  const denied=new AbortController();denied.abort(Error('cancelled'));
  await assert.rejects(restarted.context.audioBrowserDash('https://www.iq.com/play/test',globalTvid,album,denied.signal),/cancelled/);
  await restarted.send('/api/audio-settings',{enabled:false});
  assert.equal((await restarted.send('/api/audio-state?tvid='+tvid)).available,false);
  assert.equal((await restarted.context.browserAudioStream(new Request(media))).status,403,'Disabling audio revokes the previous stream');
  assert.ok(!f.fetches.some(url=>url.includes('127.0.0.1')));
  console.log('Standalone audio checks passed: exact edition/episode, browser session, gzip init, bounded ranges, CDN validation, restart, settings and no manager.');
})().catch(error=>{console.error(error);process.exitCode=1});
