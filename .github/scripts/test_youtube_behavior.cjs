#!/usr/bin/env node
'use strict';
const fs = require('node:fs');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const {execute, inspect} = require('./youtube_test_runtime.cjs');
const sourcePath = process.argv[2];
if (!sourcePath) { console.error('Usage: node regression.cjs <youtube.response.js>'); process.exit(2); }
const source = fs.readFileSync(sourcePath, 'utf8');
const audit = inspect(source), results = [];
const names = ['browse','next','player','search','reel_watch_sequence','guide','get_setting','get_watch'];
const url = route => 'https://youtubei.googleapis.com/youtubei/v1/' +
  ({reel_watch_sequence:'reel/reel_watch_sequence',get_setting:'account/get_setting'}[route] || route);
const type = route => new (audit.routes.get(route))().msgType;
const bytes = (...parts) => Uint8Array.from(parts.flatMap(p => Array.from(p)));
function vi(n) { const a=[]; do {let b=n%128;n=Math.floor(n/128);a.push(b|(n?128:0));}while(n); return a; }
const text = s => Uint8Array.from(Buffer.from(s));
const field = (n, data) => bytes(vi(n*8+2),vi(data.length),data);
function addUnknown(message, n=777, data=text('SAFE_METADATA')) {
  audit.unknown.onRead('audit',message,n,2,bytes(vi(data.length),data)); return message;
}
const unknown = m => audit.unknown.list(m).map(f => ({no:f.no,wireType:f.wireType,data:Buffer.from(f.data).toString('hex')}));
function plain(v) { return JSON.parse(JSON.stringify(v)); }
async function test(name, fn, known=false) {
  try { await fn(); results.push({name,status:known?'KNOWN':'PASS'}); }
  catch(error) { results.push({name,status:'FAIL',reason:error.message}); }
}
async function run(route, data, options={}) {
  const r=await execute(source,data,{url:url(route),...options});
  assert.equal(r.thrown,undefined,'uncaught synchronous exception');
  assert.equal(r.requests.length,0,'unexpected HTTP request');
  return r;
}
async function modified(route, message, options={}) {
  const t=type(route), input=t.toBinary(message), snapshot=bytes(input);
  const r=await run(route,input,options);
  assert.equal(r.done.length,1,'$done must be called once for binary input');
  assert.ok(r.result && r.result.body instanceof Uint8Array,'Surge output body must be Uint8Array');
  assert.equal(Object.hasOwn(r.result,'bodyBytes'),false,'must not return QuanX bodyBytes');
  assert.deepEqual(input,snapshot,'input buffer mutated');
  assert.deepEqual(Object.keys(r.result),['body'],'unexpected status/headers replacement');
  return {r,out:t.fromBinary(r.result.body),input};
}
function video(eml='video_card.eml') {
  return {videoWithContextRenderer:{videoRendererContent:{renderInfo:{layoutRender:{eml}}}}};
}
const itemSection = items => ({itemSectionRenderer:{richItemContents:items}});
const sectionContent = sections => ({sectionListRenderer:{sectionListSupportedRenderers:sections}});
function feed(route,sections) {
  const c=sectionContent(sections);
  return type(route).create(route==='next'?{content:{nextResult:{content:c}}}:{content:c});
}
function sections(route,m) {
  return (route==='next'?m.content.nextResult.content:m.content).sectionListRenderer.sectionListSupportedRenderers;
}
const items=(route,m)=>sections(route,m)[0].itemSectionRenderer.richItemContents;
function player() {
  const m=type('player').create({adPlacements:[{}],adSlots:[{}],playabilityStatus:{},playbackTracking:{
    pageadViewthroughconversion:{baseUrl:'https://ad.invalid/pagead'},
    videostatsPlaybackUrl:{baseUrl:'https://safe.invalid/playback'}}});
  addUnknown(m);addUnknown(m.playbackTracking,778,text('NORMAL_TRACKING'));
  return m;
}
(async()=>{
  await test('native Surge route map and defaults',()=>{
    assert.equal(audit.env.className,'Surge');assert.deepEqual([...audit.routes.keys()],names);
    assert.deepEqual(plain(new (audit.routes.get('browse'))().argument),{
      lyricLang:'off',captionLang:'off',blockUpload:true,blockImmersive:false,blockShorts:true,debug:false});
    assert.equal(typeof audit.context.TextEncoder,'function');assert.equal(typeof audit.context.TextDecoder,'function');
    assert.equal(audit.context.fetch,undefined);assert.equal(audit.context.window,undefined);
  });
  for(const route of names) {
    await test(route+': empty valid protobuf',async()=>{
      const r=await run(route,new Uint8Array());assert.equal(r.done.length,1);
      if(r.result.body) assert.ok(r.result.body instanceof Uint8Array);
    });
    await test(route+': malformed protobuf passthrough',async()=>{
      const r=await run(route,Uint8Array.of(255));assert.equal(r.done.length,1);assert.deepEqual(plain(r.result),{});
    });
    await test(route+': unknown field retention',async()=>{
      const t=type(route),m=addUnknown(t.create()),before=unknown(m),input=t.toBinary(m);
      const r=await run(route,input);assert.equal(r.done.length,1);
      assert.deepEqual(unknown(t.fromBinary(r.result.body || input)),before);
    });
  }
  await test('player: ads removed, metadata/unknowns kept, PIP/background enabled',async()=>{
    const m=player(),{out}=await modified('player',m);
    assert.equal(out.adPlacements.length,0);assert.equal(out.adSlots.length,0);
    assert.equal(out.playbackTracking.pageadViewthroughconversion,undefined);
    assert.equal(out.playbackTracking.videostatsPlaybackUrl.baseUrl,'https://safe.invalid/playback');
    assert.deepEqual(unknown(out),unknown(m));assert.deepEqual(unknown(out.playbackTracking),unknown(m.playbackTracking));
    assert.equal(out.playabilityStatus.pictureInPictureRender.pictureInPictureAbility.active,true);
    assert.equal(out.playabilityStatus.backgroundPlayerRender.backgroundAbility.active,true);
  });
  await test('player: nonzero-offset Uint8Array respects bounds',async()=>{
    const input=type('player').toBinary(player()),backing=new Uint8Array(input.length+16).fill(255);
    backing.set(input,7);const view=backing.subarray(7,7+input.length),copy=bytes(backing);
    const r=await run('player',view);assert.equal(r.done.length,1);
    assert.equal(type('player').fromBinary(r.result.body).adSlots.length,0);assert.deepEqual(backing,copy);
  });
  for(const route of ['browse','next','search']) {
    await test(route+': ad/Shorts/shopping items removed; normal video retained',async()=>{
      const m=addUnknown(feed(route,[itemSection([video(),video('inline_injection_entrypoint_layout.eml'),
        video('shorts_shelf.eml'),video('shopping_item_card.eml'),video('Sponsored_content')])]));
      addUnknown(items(route,m)[0].videoWithContextRenderer,778);
      const {out}=await modified(route,m);assert.equal(items(route,out).length,1);
      assert.equal(items(route,out)[0].videoWithContextRenderer.videoRendererContent.renderInfo.layoutRender.eml,'video_card.eml');
      assert.deepEqual(unknown(out),unknown(m));
      assert.deepEqual(unknown(items(route,out)[0].videoWithContextRenderer),unknown(items(route,m)[0].videoWithContextRenderer));
    });
    await test(route+': Shorts shelf and nonvideo section removed',async()=>{
      const m=feed(route,[itemSection([video()]),{shelfRenderer:{richSectionContent:{reelShelfRenderer:{richItemContents:[]}}}},itemSection([{}])]);
      const {out}=await modified(route,m);assert.equal(sections(route,out).length,1);
    });
    await test(route+': text-only shopping section removed',async()=>{
      const m=feed(route,[itemSection([video()]),{musicDescriptionShelfRenderer:{description:{runs:[{text:'shopping_timely_shelf'}]}}}]);
      const {out}=await modified(route,m);assert.equal(sections(route,out).length,1);
    });
  }
  await test('guide: default hides Premium/upload/Shorts; keeps ordinary and immersive',async()=>{
    const m=addUnknown(type('guide').create({labelItems:[{guideSectionRenderer:{rendererItems:
      ['FEhome','SPunlimited','FEuploads','FEshorts','FEmusic_immersive'].map(browseId=>({labelRender:{browseId}}))}}]}));
    const {out}=await modified('guide',m);
    assert.deepEqual(plain(out.labelItems[0].guideSectionRenderer.rendererItems.map(x=>x.labelRender.browseId)),['FEhome','FEmusic_immersive']);
    assert.deepEqual(unknown(out),unknown(m));
  });
  await test('guide: custom JSON argument changes only selected switches',async()=>{
    const m=type('guide').create({iconItems:[{guideSectionRenderer:{rendererItems:
      ['FEhome','SPunlimited','FEuploads','FEshorts','FEmusic_immersive'].map(browseId=>({iconRender:{browseId}}))}}]});
    const {out}=await modified('guide',m,{argument:JSON.stringify({blockShorts:false,blockUpload:false,blockImmersive:true})});
    assert.deepEqual(plain(out.iconItems[0].guideSectionRenderer.rendererItems.map(x=>x.iconRender.browseId)),['FEhome','FEuploads','FEshorts']);
  });
  await test('reel: removes entries without overlay, preserves legitimate reel and metadata',async()=>{
    const m=addUnknown(type('reel_watch_sequence').create({entries:[{}, {command:{reelWatchEndpoint:{overlay:{}}}}]}));
    addUnknown(m.entries[1],778);const {out}=await modified('reel_watch_sequence',m);
    assert.equal(out.entries.length,1);assert.ok(out.entries[0].command.reelWatchEndpoint.overlay);
    assert.deepEqual(unknown(out.entries[0]),unknown(m.entries[1]));assert.deepEqual(unknown(out),unknown(m));
  });
  await test('setting: background/download flags and category toggle; metadata preserved',async()=>{
    const m=addUnknown(type('get_setting').create({settingItems:[{settingCategoryCollectionRenderer:{categoryId:10135,name:{runs:[{text:'LOCAL_SAFE'}]}}}]}));
    const {out}=await modified('get_setting',m);assert.equal(out.settingItems.length,2);
    const c=out.settingItems[0].settingCategoryCollectionRenderer;
    assert.equal(c.name.runs[0].text,'LOCAL_SAFE');assert.equal(c.subSettings[0].settingBooleanRenderer.enableServiceEndpoint.setClientSettingEndpoint.settingData.clientSettingEnum.item,151);
    const b=out.settingItems[1].backgroundPlayBackSettingRenderer;
    for(const k of ['backgroundPlayback','download','downloadQualitySelection','smartDownload'])assert.equal(b[k],true);
    assert.deepEqual(unknown(out),unknown(m));
  });
  await test('get_watch: nested player and next both cleaned',async()=>{
    const m=addUnknown(type('get_watch').create({contents:[{player:player(),next:feed('next',[itemSection([video(),video('shopping_item_card')])])}]}));
    const {out}=await modified('get_watch',m);assert.equal(out.contents[0].player.adPlacements.length,0);
    assert.equal(items('next',out.contents[0].next).length,1);assert.deepEqual(unknown(out),unknown(m));
  });
  await test('browse: top-level opaque shopping card removed; sibling bytes retained',async()=>{
    const m=feed('browse',[itemSection([video()])]);
    addUnknown(m,778,bytes(field(1,text('shopping_item_card')),field(2,text('SAFE_SIBLING_METADATA'))));
    const {out}=await modified('browse',m);const data=audit.unknown.list(out)[0].data;
    assert.ok(Buffer.from(data).includes(Buffer.from('SAFE_SIBLING_METADATA')));
    assert.ok(!Buffer.from(data).includes(Buffer.from('shopping_item_card')));
  });
  await test('browse: .eml template identifier alone not stripped from opaque metadata',async()=>{
    const m=feed('browse',[itemSection([video()])]);addUnknown(m,778,field(1,text('shopping_item_card.eml')));
    const input=type('browse').toBinary(m),r=await run('browse',input);
    assert.deepEqual(unknown(type('browse').fromBinary(r.result.body||input)),unknown(m));
  });
  await test('browse: unknown ad field learned in isolated local storage',async()=>{
    const m=feed('browse',[itemSection([video(),{}])]);
    addUnknown(items('browse',m)[1],48602820,text('x'.repeat(1100)+'pagead'));
    const {out,r}=await modified('browse',m);assert.equal(items('browse',out).length,1);
    assert.equal(r.writes.length,1);assert.equal(r.writes[0].key,'YouTubeAdvertiseInfo');
    assert.ok(JSON.parse(r.writes[0].value).blackNo.includes(48602820));
  });
  await test('browse: library junk (SPunlimited) removed even when too small for ad learner',async()=>{
    const m=feed('browse',[itemSection([video(),{}])]);addUnknown(items('browse',m)[1],79129962,text('SPunlimited_LOCAL_METADATA'));
    const {out}=await modified('browse',m);assert.equal(items('browse',out).length,1);
  });
  await test('browse: raw 最相关 renderer pruned; unrelated unknown sibling retained',async()=>{
    const normal=field(1,field(100,text('SAFE_METADATA')));
    const related=field(1,field(312131490,field(1,text('最相关'))));
    const input=field(777,field(49399797,bytes(related,normal)));
    const r=await run('browse',input);assert.ok(r.result.body instanceof Uint8Array);
    assert.ok(!Buffer.from(r.result.body).includes(Buffer.from('最相关')));
    assert.ok(Buffer.from(r.result.body).includes(Buffer.from('SAFE_METADATA')));
  });
  for(const bad of [undefined,null,42,'{"adPlacements":[{}]}',{},[],new ArrayBuffer(1)]) {
    await test('non-Uint8Array body passes through: '+Object.prototype.toString.call(bad),async()=>{
      const r=await run('player',bad);assert.ok(r.done.length>=1);
      assert.ok(r.done.every(d=>!d||!Object.hasOwn(d,'body')));
    });
  }
  await test('JSON bytes are not parsed as JSON; safe passthrough',async()=>{
    const r=await run('player',text('{"adPlacements":[{}]}'));
    assert.equal(r.done.length,1);assert.deepEqual(plain(r.result),{});
  });
  await test('malformed argument falls back without modifying body',async()=>{
    const r=await run('player',type('player').toBinary(player()),{argument:'not-json'});
    assert.equal(r.done.length,1);assert.deepEqual(plain(r.result),{});
  });
  await test('corrupted in-memory cache falls back without modifying body',async()=>{
    const r=await run('player',type('player').toBinary(player()),{storage:{YouTubeAdvertiseInfo:'not-json'}});
    assert.equal(r.done.length,1);assert.deepEqual(plain(r.result),{});
  });
  await test('KNOWN: missing body causes duplicate $done calls in VM',async()=>{
    const r=await run('player',undefined);assert.equal(r.done.length,2);
    assert.ok(r.done.every(d=>Object.keys(d).length===0));
  },true);
  await test('KNOWN: substring route dispatch can be confused by query text',()=>{
    assert.equal(audit.getRoute(url('player')+'?hint=browse').name,'Browse');
  },true);
  await test('KNOWN: blockShorts=false does not disable hardcoded EML Shorts filter',async()=>{
    const m=feed('browse',[itemSection([video(),video('shorts_shelf.eml')])]);
    const {out}=await modified('browse',m,{argument:'{"blockShorts":false}'});
    assert.equal(items('browse',out).length,1);
  },true);
  await test('browse: section-level opaque chips card removed; ordinary item retained',async()=>{
    const m=feed('browse',[itemSection([video()])]);
    addUnknown(sections('browse',m)[0],778,field(1,text('chips_shelf_content_ad')));
    m.content.sectionListRenderer.sectionListSupportedRenderers.push(itemSection([video()]));
    const {out}=await modified('browse',m);assert.equal(sections('browse',out).length,1);
  });
  await test('browse: unknown chips children removed, field-1 safe sibling preserved',async()=>{
    const m=feed('browse',[itemSection([video()])]);
    addUnknown(m.content.sectionListRenderer,778,bytes(field(1,text('chips_shelf_content_ad')),field(1,text('SAFE_SIBLING'))));
    const {out}=await modified('browse',m),b=Buffer.from(audit.unknown.list(out.content.sectionListRenderer)[0].data);
    assert.ok(!b.includes(Buffer.from('chips_shelf_content_')));assert.ok(b.includes(Buffer.from('SAFE_SIBLING')));
  });
  await test('browse: pagead-bearing section-list unknown field dropped; safe unknown kept',async()=>{
    const m=feed('browse',[itemSection([video()])]),s=m.content.sectionListRenderer;
    addUnknown(s,778,text('opaque_pagead_advertisement_record'));addUnknown(s,779,text('SAFE_UNKNOWN'));
    const {out}=await modified('browse',m);assert.deepEqual(unknown(out.content.sectionListRenderer),unknown(s).filter(x=>x.no===779));
  });
  await test('browse: large opaque pagead child removed; metadata retained',async()=>{
    const m=feed('browse',[itemSection([video()])]);
    addUnknown(m,778,field(1,bytes(field(1,text('x'.repeat(10001)+'pagead')),field(1,text('SAFE_NESTED')))));
    const {out}=await modified('browse',m),b=Buffer.from(audit.unknown.list(out)[0].data);
    assert.ok(!b.includes(Buffer.from('pagead')));assert.ok(b.includes(Buffer.from('SAFE_NESTED')));
  });
  await test('KNOWN: chips filter discards non-field-1 sibling in rewritten opaque message',async()=>{
    const m=feed('browse',[itemSection([video()])]);
    addUnknown(m.content.sectionListRenderer,778,bytes(field(1,text('chips_shelf_content_ad')),field(2,text('SAFE_NON_ONE_METADATA'))));
    const {out}=await modified('browse',m),b=Buffer.from(audit.unknown.list(out.content.sectionListRenderer)[0].data);
    assert.equal(b.includes(Buffer.from('SAFE_NON_ONE_METADATA')),false);
  },true);
  await test('KNOWN: engagementPanels is not a known protobuf field in these route schemas',()=>{
    const seen=new Set();function walk(t){if(seen.has(t.typeName))return;seen.add(t.typeName);
      for(const f of t.fields){assert.notEqual(f.localName,'engagementPanels');if(f.kind==='message')walk(f.T());}}
    for(const route of ['browse','next','search'])walk(type(route));
  },true);
  await test('KNOWN: captionLang option does not invoke dormant caption translator',async()=>{
    const m=player();m.captions=type('player').create({captions:{playerCaptionsTrackListRenderer:{captionTracks:[{
      baseUrl:'https://safe.invalid/caption',languageCode:'en',vssId:'.en',name:{runs:[{text:'English'}]}}]}}}).captions;
    const {out}=await modified('player',m,{argument:'{"captionLang":"zh-Hans"}'});
    assert.equal(out.captions.playerCaptionsTrackListRenderer.captionTracks.length,1);
    assert.equal(out.captions.playerCaptionsTrackListRenderer.captionTracks[0].languageCode,'en');
  },true);
  await test('KNOWN: standalone player has no general opaque shopping-card filter',async()=>{
    const m=player();addUnknown(m,779,field(1,text('shopping_item_card')));
    const {out}=await modified('player',m);
    assert.ok(audit.unknown.list(out).some(f=>Buffer.from(f.data).includes(Buffer.from('shopping_item_card'))));
  },true);
  await test('browse: default lyricLang=off prevents translation IO on lyrics page',async()=>{
    const m=feed('browse',[itemSection([video()])]);
    m.responseContext=type('browse').create({responseContext:{serviceTrackingParams:[{service:1,params:[{key:'browse_id',value:'MPLYt_LOCAL_ONLY'}]}]}}).responseContext;
    const r=await run('browse',type('browse').toBinary(m));assert.equal(r.done.length,1);
  });
  for(const route of names) await test(route+': invalid tag/truncated message/JSON byte passthrough',async()=>{
    for(const b of [Uint8Array.of(0),Uint8Array.of(10,9,1),Uint8Array.of(15),text('{"adPlacements":[{}]}')]){
      const r=await run(route,b);assert.equal(r.done.length,1);assert.deepEqual(plain(r.result),{});
    }
  });
  const summary={sha256:crypto.createHash('sha256').update(source).digest('hex'),sourceBytes:Buffer.byteLength(source),
    pass:results.filter(r=>r.status==='PASS').length,known:results.filter(r=>r.status==='KNOWN').length,
    fail:results.filter(r=>r.status==='FAIL').length,tests:results};
  console.log(JSON.stringify(summary,null,2));process.exitCode=summary.fail?1:0;
})().catch(error=>{console.error(error.message);process.exitCode=1;});
