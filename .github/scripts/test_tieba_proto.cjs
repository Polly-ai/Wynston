'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const sourcePath = process.argv[2] || path.resolve(__dirname, '../../Surge/JavaScript/TieBa/tieba-proto.js');
const source = fs.readFileSync(sourcePath, 'utf8');
const split = source.indexOf('const resStatus =');
assert.ok(split > 0, 'Expected upstream runtime boundary');
const quiet = {log() {}, warn() {}, error() {}};
const schema = vm.createContext({console: quiet});
vm.runInContext(source.slice(0, split), schema, {timeout: 5000});
const type = name => vm.runInContext(name, schema);
const encode = (name, data) => type(name).toBinary(type(name).create(data));
// The bundled TextDecoder uses `buffer instanceof ArrayBuffer`. VM realms
// have distinct constructors: transplanting a typed array silently decodes
// strings as empty. Recreate bytes in the consuming realm, as a real Surge
// response would be, and preserve offsets to exercise QX's buffer slicing.
function realmBytes(context, bytes) {
  if (!ArrayBuffer.isView(bytes)) return bytes;
  context.__fixtureBuffer = Array.from(new Uint8Array(bytes.buffer));
  const local = vm.runInContext(`Uint8Array.from(__fixtureBuffer).subarray(${bytes.byteOffset}, ${bytes.byteOffset + bytes.byteLength})`, context);
  delete context.__fixtureBuffer;
  return local;
}
const decode = (name, bytes) => type(name).fromBinary(realmBytes(schema, bytes));
function run(route, bytes, options = {}) {
  const calls = [], notices = [], logs = [];
  const globals = {console: {log(...args) {logs.push(args.join(' '));}, warn() {}, error() {}},
    $request: {url: 'https://tiebac.baidu.com/c/' + route},
    $response: {status: 200}, $done(value) {calls.push(value);},
    $notification: {post(...args) {notices.push(args);}}};
  if ('argument' in options) globals.$argument = options.argument;
  if ('status' in options) globals.$response.status = options.status;
  const context = vm.createContext(globals);
  const localBytes = realmBytes(context, bytes);
  globals.$response.body = localBytes;
  if (options.quanx) {globals.$task = {}; globals.$response.bodyBytes = localBytes.buffer.slice(localBytes.byteOffset, localBytes.byteOffset + localBytes.byteLength); delete globals.$response.body;}
  let error;
  try {vm.runInContext(source, context, {timeout: 5000});} catch (e) {error = e;}
  return {calls, notices, logs, error, input: localBytes};
}
let passed = 0;
function test(name, fn) {fn(); passed++; console.log('PASS ' + name);}
function body(result) {assert.ifError(result.error); assert.equal(result.calls.length, 1); return result.calls[0].body;}
const route = 'f/excellent/personalized?cmd=303002';
const input = encode('PersonalizedResIdl', {data: {bannerList: {app: [{goodsInfo: [{id: 7}]}]}, threadList: [{}, {alaInfo: {liveId: '1'}}, {videoInfo: {videoMd5: 'video'}}], liveAnswer: {bannerUrl: 'advert'}}});
test('Surge binary output; default keeps video, removes live, goods and banner', () => {
  const out = body(run(route, input));
  assert.equal(Object.prototype.toString.call(out), '[object Uint8Array]');
  const data = decode('PersonalizedResIdl', out).data;
  assert.equal(data.threadList.length, 2); assert.ok(data.threadList[1].videoInfo);
  assert.equal(data.threadList[1].videoInfo.videoMd5, 'video');
  assert.equal(data.bannerList.app[0].goodsInfo.length, 0); assert.equal(data.liveAnswer, undefined);
});
for (const argument of ['per_filter_video_thread=1', {per_filter_video_thread: 1}]) test('Video filtering argument ' + JSON.stringify(argument), () => {
  assert.equal(decode('PersonalizedResIdl', body(run(route, input, {argument}))).data.threadList.length, 1);
});
test('Zero argument keeps video', () => {assert.equal(decode('PersonalizedResIdl', body(run(route, input, {argument: 'per_filter_video_thread=0'}))).data.threadList.length, 2);});
test('Non-200 response passes through', () => {const r = run(route, input, {status: 204}); assert.ifError(r.error); assert.equal(r.calls.length, 1); assert.deepEqual(Object.keys(r.calls[0]), []);});
test('Unknown pb command preserves exact bytes and subarray boundaries', () => {
  const raw = Uint8Array.from([99, 0, 128, 255, 1, 88]).subarray(1, 5);
  const r = run('f/pb/page?cmd=999', raw);
  assert.strictEqual(body(r), r.input);
  assert.equal(r.input.byteOffset, 1); assert.equal(r.input.buffer.byteLength, 6);
  assert.deepEqual(Array.from(body(r)), Array.from(raw));
  const q = run('f/pb/page?cmd=999', raw, {quanx: true}); assert.ifError(q.error);
  assert.deepEqual(Array.from(new Uint8Array(q.calls[0].bodyBytes)), Array.from(raw));
});
test('Unknown protobuf fields survive modifications', () => {
  const unknown = Uint8Array.from([0xa0, 0x06, 0x96, 0x01]); // field 100 = 150
  const extended = Uint8Array.from([...input, ...unknown]);
  const out = body(run(route, extended));
  assert.ok(Buffer.from(out).includes(Buffer.from(unknown)));
});
test('frs page removes live feeds and ads, retains video and ordinary feed', () => {
  const bytes = encode('FrsPageResIdl', {data: {forum: {bannerList: {app: [{goodsInfo: [{id: 8}]}]}}, threadList: [{}, {alaInfo: {}}, {videoInfo: {}}], liveFuseForum: [{onlineUsers: '1'}], activityhead: {isAd: true}, pageData: {feedList: [{feed: {businessInfo: [{key: 'is_live_card', value: '1'}]}}, {feed: {businessInfo: [{key: 'is_live_card', value: '0'}]}}, {}]}}});
  const r = run('f/frs/page?cmd=1', bytes);
  const data = decode('FrsPageResIdl', body(r)).data;
  assert.ok(r.logs.some(line => line.includes('去除frs帖子直播1')));
  assert.equal(data.forum.bannerList.app[0].goodsInfo.length, 0);
  assert.equal(data.threadList.length, 2); assert.equal(data.liveFuseForum.length, 0);
  assert.equal(data.activityhead, undefined); assert.equal(data.pageData.feedList.length, 2);
  assert.equal(data.pageData.feedList[0].feed.businessInfo[0].key, 'is_live_card');
  assert.equal(data.pageData.feedList[0].feed.businessInfo[0].value, '0');
  assert.equal(data.pageData.feedList[1].feed, undefined);
});
test('Old pb removes banner goods, live ad and post promotions', () => {
  const bytes = encode('PbPageResIdl', {data: {bannerList: {app: [{goodsInfo: [{id: 1}]}], pbBannerAd: {goodsInfo: [{id: 2}], liveAd: {}}}, recomAlaInfo: {liveId: '1'}, postList: [{outerItem: {}, novelRecomCard: {}}]}});
  const data = decode('PbPageResIdl', body(run('f/pb/page?cmd=302001', bytes))).data;
  assert.equal(data.bannerList.app[0].goodsInfo.length, 0);
  assert.equal(data.bannerList.pbBannerAd.goodsInfo.length, 0);
  assert.equal(data.bannerList.pbBannerAd.liveAd, undefined); assert.equal(data.recomAlaInfo, undefined);
  assert.equal(data.postList[0].outerItem, undefined); assert.equal(data.postList[0].novelRecomCard, undefined);
});
test('New pb list removes novel recommendation', () => {
  const bytes = encode('PbListResIdl', {data: {firstFloor: {novelRecomCard: {}}}});
  assert.equal(decode('PbListResIdl', body(run('f/pb/page?cmd=309751', bytes))).data.firstFloor.novelRecomCard, undefined);
});
for (const [name, url, data, getApps] of [
  ['ThreadListResIdl', 'f/frs/threadlist?cmd=1', {bannerList: {app: [{goodsInfo: [{id: 1}]}]}}, d => d.bannerList.app],
  ['GeneralTabListResIdl', 'f/frs/generalTabList?cmd=1', {appList: [{goodsInfo: [{id: 1}]}]}, d => d.appList],
  ['GetFeedAdResIdl', 'f/ad/getFeedAd?cmd=1', {recom: [{goodsInfo: [{id: 1}]}], frs: [{goodsInfo: [{id: 2}]}]}, d => [...d.recom, ...d.frs]],
  ['AdBidResIdl', 'b/ad/adBid?cmd=1', {bannerList: {app: [{goodsInfo: [{id: 1}]}], pbBannerAd: {}}}, d => d.bannerList.app]
]) test(name + ' removes goods', () => {
  const dataOut = decode(name, body(run(url, encode(name, {data})))).data;
  assert.ok(getApps(dataOut).every(app => app.goodsInfo.length === 0));
  if (name === 'AdBidResIdl') assert.equal(dataOut.bannerList.pbBannerAd, undefined);
});
test('QX branch emits ArrayBuffer containing cleaned protobuf', () => {
  const r = run(route, input, {quanx: true}); assert.ifError(r.error); assert.equal(r.calls.length, 1);
  assert.equal(Object.prototype.toString.call(r.calls[0].bodyBytes), '[object ArrayBuffer]');
  assert.equal(decode('PersonalizedResIdl', new Uint8Array(r.calls[0].bodyBytes)).data.threadList.length, 2);
});
test('Missing or malformed body raises before done (upstream limitation)', () => {
  for (const bytes of [undefined, 'text', Uint8Array.from([0xff])]) {
    const r = run(route, bytes); assert.ok(r.error); assert.equal(r.calls.length, 0);
  }
});
test('Empty protobuf without data raises before done (upstream limitation)', () => {const r = run(route, new Uint8Array()); assert.ok(r.error); assert.equal(r.calls.length, 0);});
test('Status string is ignored due to strict numeric comparison (upstream limitation)', () => {const r = run(route, input, {status: '200'}); assert.ifError(r.error); assert.deepEqual(Object.keys(r.calls[0]), []);});
test('UTF-8 and nonzero-offset protobuf retain strings in both environments', () => {
  const text = '贴吧🙂\u0000end';
  const bytes = encode('PersonalizedResIdl', {data: {threadList: [{videoInfo: {videoMd5: text}}]}});
  const padded = Uint8Array.from([99, ...bytes, 88]).subarray(1, bytes.length + 1);
  for (const quanx of [false, true]) {
    const r = run(route, padded, {quanx}); assert.ifError(r.error); assert.equal(r.calls.length, 1);
    const out = quanx ? new Uint8Array(r.calls[0].bodyBytes) : body(r);
    assert.equal(decode('PersonalizedResIdl', out).data.threadList[0].videoInfo.videoMd5, text);
  }
});
test('Cross-realm polyfill limitation is isolated from response fixtures', () => {
  // Directly transplanting bytes was the original frs test bug. Demonstrate
  // the exact failure without treating it as a real same-realm Surge failure.
  schema.__foreignBytes = Uint8Array.from([0x41]);
  try {assert.equal(vm.runInContext('new TextDecoder().decode(__foreignBytes)', schema), '');}
  finally {delete schema.__foreignBytes;}
  schema.__localBytes = realmBytes(schema, Uint8Array.from([0x41]));
  try {assert.equal(vm.runInContext('new TextDecoder().decode(__localBytes)', schema), 'A');}
  finally {delete schema.__localBytes;}
});
console.log(`${passed} tests passed: ${sourcePath}`);
