'use strict';
// Full ORIGINAL script executes in Surge-like VM: no network, Node/process, real storage or timers.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const filename = process.argv[2] || path.resolve(__dirname, '../../Surge/JavaScript/XiaoHongShu/redbook.ads.js');
const configFile = process.argv[3];
const original = fs.readFileSync(filename, 'utf8');
const compiled = new vm.Script(original, {filename: 'ORIGINAL-redbook.ads.js'});
const rootUrl = 'https://edith.xiaohongshu.com/api/sns/v1/';
const stores = Object.create(null);
let runs = 0;
function execute(endpoint, input, store = Object.create(null)) {
  const body = typeof input === 'string' ? input : JSON.stringify(input);
  const calls = [], logs = [];
  let forbidden = 0;
  const deny = () => { forbidden++; throw new Error('OFFLINE: network/timers forbidden'); };
  const context = vm.createContext({
    $environment: {'surge-version': '5.9.1'},
    $request: {url: rootUrl + endpoint, method: 'GET', headers: {}},
    $response: {body, status: 200, headers: {'Content-Type': 'application/json'}},
    $persistentStore: {read(key) { return store[key] ?? null; },
      write(value, key) { store[key] = String(value); return true; }},
    $httpClient: {get: deny, post: deny},
    $notification: {post: deny},
    $done(value) { calls.push(JSON.parse(JSON.stringify(value || {}))); },
    console: {log(...args) { logs.push(args.join(' ')); }},
    setTimeout: deny, setInterval: deny,
  }, {codeGeneration: {strings: false, wasm: false}});
  compiled.runInContext(context, {timeout: 1500});
  runs++;
  assert.equal(forbidden, 0, endpoint + ': unexpected external capability');
  assert.ok(calls.length >= 1, endpoint + ': script did not complete');
  const output = calls[0].body ?? body; // Surge takes the first completion.
  return {body: output, json() { return JSON.parse(output); }, calls, logs};
}
const keep = {trace: 'retained', success: true, code: 0};
const envelope = data => ({...keep, data});
const saving = {disable_save: false, disable_watermark: true, disable_weibo_cover: true};
const functions = ['video_download', 'generate_image', 'copy_link', 'native_voice', 'video_speed', 'dislike', 'report', 'video_feedback'];
function checkKeep(result) {
  for (const [key, value] of Object.entries(keep)) assert.deepEqual(result[key], value);
}
const cases = [];
function fixture(endpoint, data, check) {
  const value = execute(endpoint, envelope(data), stores).json();
  checkKeep(value); check(value.data); cases.push(endpoint);
}
fixture('note/tabfeed?x=1', {items: [{id:'tab-video', related_goods_num:2, has_related_goods:true,
  media_save_config:{disable_save:true}, share_info:{retain:'yes',function_entries:[{type:'ads'}]},
  function_switch:[{type:'download',enable:false,reason:'paywall'}],
  video_info_v2:{media:{stream:{h265:[{master_url:'https://video.example/tab-clean.mp4'}]}}}, title:'keep'}]}, data => {
  const item=data.items[0]; assert.equal(item.title,'keep'); assert.equal(item.related_goods_num,0);
  assert.equal(item.has_related_goods,false); assert.deepEqual(item.media_save_config,saving);
  assert.equal(item.share_info.retain,'yes'); assert.deepEqual(item.share_info.function_entries.map(x=>x.type),functions);
  assert.deepEqual(item.function_switch,[{type:'download',enable:true}]);
});
fixture('note/videofeed?x=1', [{id:'video', related_goods_num:1, has_related_goods:true,
  media_save_config:{disable_save:true}, share_info:{function_entries:[]},
  function_switch:[{type:'download',enable:false,reason:'blocked'}],
  video_info_v2:{media:{stream:{h265:[{master_url:'https://video.example/clean.mp4'}]}}}, title:'normal video'}], data => {
  assert.equal(data[0].title,'normal video'); assert.equal(data[0].related_goods_num,0);
  assert.equal(data[0].has_related_goods,false); assert.deepEqual(data[0].media_save_config,saving);
  assert.deepEqual(data[0].function_switch,[{type:'download',enable:true}]);
});
fixture('note/video/save?x=1', {note_id:'video',status:0,download_url:'https://video.example/watermarked.mp4'}, data => {
  assert.deepEqual(data,{status:2,note_id:'video',download_url:'https://video.example/clean.mp4'});
});
fixture('note/imagefeed?x=1', {items:[{related_goods_num:3,has_related_goods:true,note_list:[{id:'photo',
  images_list:[{url:'https://image.example/original.jpg',live_photo_file_id:'file-id',live_photo:{media:{video_id:'live-id',
    stream:{h265:[{master_url:'https://video.example/live-clean.mp4'}]}}}}]}]}]}, data => {
  const item=data.items[0]; assert.equal(item.related_goods_num,0); assert.equal(item.has_related_goods,false);
  assert.deepEqual(item.note_list[0].media_save_config,saving);
  assert.equal(item.note_list[0].images_list[0].url,'https://image.example/original.jpg');
});
fixture('note/live_photo/save?x=1', {datas:[{url:'https://video.example/live-watermarked.mp4'}],retain:'yes'}, data => {
  assert.equal(data.retain,'yes'); assert.deepEqual(data.datas,[{video_id:'live-id',file_id:'file-id',url:'https://video.example/live-clean.mp4'}]);
});
fixture('note/feed?x=1', [{title:'retain',related_goods_num:7,has_related_goods:true,
  function_switch:[{enable:false,reason:'deny'}],note_list:[{id:'normal-picture',image_url:'https://image.example/keep.jpg'}]}], data => {
  assert.equal(data[0].title,'retain'); assert.equal(data[0].related_goods_num,0); assert.equal(data[0].has_related_goods,false);
  assert.deepEqual(data[0].function_switch,[{enable:true}]); assert.deepEqual(data[0].note_list[0].media_save_config,saving);
  assert.equal(data[0].note_list[0].image_url,'https://image.example/keep.jpg');
});
fixture('note/redtube?x=1', {items:[{id:'retain',related_goods_num:8,has_related_goods:true,
  media_save_config:{disable_save:true},share_info:{function_entries:[{type:'ads'}]}}]}, data => {
  assert.equal(data.items[0].id,'retain'); assert.equal(data.items[0].related_goods_num,0);
  assert.equal(data.items[0].has_related_goods,false); assert.deepEqual(data.items[0].media_save_config,saving);
  assert.deepEqual(data.items[0].share_info.function_entries.map(x=>x.type),functions);
});
fixture('search/notes?x=1', {retain:'yes',items:[{id:'normal',title:'keep'},{id:'ad',ads:{ad_id:1}},{id:'normal2',ads:null}]}, data => {
  assert.equal(data.retain,'yes'); assert.deepEqual(data.items.map(x=>x.id),['normal','normal2']);
});
fixture('note/widgets?x=1', {ad_banner:'remove',widgets:[{id:1}]}, data => assert.deepEqual(data,{}));
fixture('system_service/splash_config?x=1', {retain:'yes',ads_groups:[{start_time:'old',end_time:'old',ads:[{start_time:'old',end_time:'old',keep:'yes'}]}]}, data => {
  assert.equal(data.retain,'yes'); assert.equal(data.ads_groups[0].start_time,'2208963661');
  assert.equal(data.ads_groups[0].end_time,'2209050061');
  assert.equal(data.ads_groups[0].ads[0].start_time,'2208963661');
  assert.equal(data.ads_groups[0].ads[0].end_time,'2209050061'); assert.equal(data.ads_groups[0].ads[0].keep,'yes');
});
fixture('homefeed?x=1', [{id:'keep',title:'normal'},{id:'ads',is_ads:true},{id:'keep2',is_ads:false}], data => {
  assert.deepEqual(data,[{id:'keep',title:'normal'},{id:'keep2',is_ads:false}]);
});
fixture('system_service/config?x=1', {store:{ad:1},splash:1,loading_img:'ads',app_theme:{ad:1},cmt_words:['ad'],
  highlight_tab:{ad:1},watermark_pic_path:'https://image.example/watermark.png',normal:{retain:1}}, data => {
  assert.deepEqual(data,{normal:{retain:1}});
});
fixture('search/hot_list?x=1', {items:[{id:'ad'}],title:'promoted'}, data => {
  assert.deepEqual(data,{scene:'',title:'',items:[],host:'',background_color:{},word_request_id:''});
});
fixture('search/hint?x=1', {retain:'yes',hint_words:[{title:'promoted'}]}, data => {
  assert.equal(data.retain,'yes'); assert.deepEqual(data.hint_words,[{title:'搜索笔记',type:'firstEnterOther#itemCfRecWord#搜索笔记#1',search_word:'搜索笔记'}]);
});
fixture('homefeed/categories?x=1', {retain:'yes',categories:[{oid:'homefeed.shop'},{oid:'homefeed.sketch'},
  {oid:'homefeed.live'},{oid:'homefeed.recommend',title:'keep'}]}, data => {
  assert.equal(data.retain,'yes'); assert.deepEqual(data.categories,[{oid:'homefeed.recommend',title:'keep'}]);
});
fixture('search/trending?x=1', {title:'promoted',queries:[{id:'ad'}]}, data => {
  assert.deepEqual(data,{title:'',queries:[],type:'',word_request_id:''});
});
// Disabled upstream endpoint is tested but never enabled in the module.
const disabled='note/comment/list?x=1';
const comments=execute(disabled,envelope({comments:[{id:'keep',user:{user_id:'opaque',red_id:'real',retain:1},
  pictures:[{url:'watermarked',origin_url:'watermarked',meme_package:{image_url:'original'},retain:1}]}]})).json();
assert.deepEqual(comments.data.comments[0].user,{user_id:'real',retain:1});
assert.equal(comments.data.comments[0].pictures[0].url,'original');
assert.equal(comments.data.comments[0].pictures[0].origin_url,'original');
// Every registered endpoint: malformed JSON, null, missing fields, and empty response must complete safely.
for (const endpoint of [...cases,disabled]) {
  for (const bad of ['not-json','{broken','', 'null']) {
    assert.equal(execute(endpoint,bad).body,bad,endpoint+': malformed/null must fail open');
  }
  for (const missing of [{},{data:{}},{data:null}]) {
    const result=execute(endpoint,missing).json();
    assert.ok(result!==undefined,endpoint+': missing fields must be safe');
  }
}
// Without a saved video the original catches the missing-cache TypeError and keeps the server response.
const uncached=envelope({note_id:'uncached',download_url:'watermarked',status:0});
assert.deepEqual(execute('note/video/save?',uncached).json(),uncached);
// Upstream live-photo save uses JSON.parse(null) when cache is absent: null, not invented URLs.
assert.equal(execute('note/live_photo/save?',envelope({datas:['original']})).json().data.datas,null);
// Caches retain 100 most recent entries, tolerate corrupted cache and preserve unrelated persistent keys.
const capStore={'redbook_user_video_key':JSON.stringify(Array.from({length:100},(_,i)=>({note_id:'old'+i}))),local_setting:'keep'};
execute('note/tabfeed?',envelope({items:[{id:'new',video_info_v2:{media:{stream:{h265:[{master_url:'clean'}]}}}}]}),capStore);
assert.equal(JSON.parse(capStore.redbook_user_video_key).length,100);
assert.equal(JSON.parse(capStore.redbook_user_video_key)[0].note_id,'old1');
assert.equal(capStore.local_setting,'keep');
const corrupt={'redbook_user_video_key':'not-json'};
execute('note/tabfeed?',envelope({items:[]}),corrupt);
assert.deepEqual(JSON.parse(corrupt.redbook_user_video_key),[]);
const photoStore={'redbook_user_photo_key':JSON.stringify(Array.from({length:100},(_,i)=>({video_id:'old'+i})))};
execute('note/imagefeed?',envelope([{note_list:[{images_list:[{live_photo_file_id:'new-file',live_photo:{media:{video_id:'new-video',
  stream:{h265:[{master_url:'clean'}]}}}}]}]}]),photoStore);
assert.equal(JSON.parse(photoStore.redbook_user_photo_key).length,100);
assert.equal(JSON.parse(photoStore.redbook_user_photo_key)[0].video_id,'old1');
// Verify the actual URL expressions from config still reach all tested endpoints.
if(configFile) {
  const lines=fs.readFileSync(configFile,'utf8').split(/\r?\n/);
  const scripts=lines.filter(x=>!x.startsWith(';')&&x.includes(' url script-response-body '));
  const rejects=lines.filter(x=>!x.startsWith(';')&&x.includes(' url reject-200'));
  assert.equal(scripts.length,16); assert.equal(rejects.length,9);
  for(const endpoint of cases) {
    const url=rootUrl+endpoint;
    assert.equal(scripts.filter(x=>new RegExp(x.split(' url ')[0]).test(url)).length,1,'rule coverage: '+endpoint);
  }
  const splash=rootUrl+'system_service/splash_config?x=1';
  assert.ok(rejects.some(x=>new RegExp(x.split(' url ')[0]).test(splash)), 'upstream splash overlap must stay');
  assert.equal(lines.filter(x=>x.startsWith(';')&&x.includes('note\\/comment\\/list')).length,1);
}
console.log(`PASS: ORIGINAL native Surge JS, 16 active endpoints + disabled comment fixture; ${runs} isolated runs, ad removal/keep, picture/video/live watermark, cache bounds, malformed JSON, missing fields; no bridge required.`);
