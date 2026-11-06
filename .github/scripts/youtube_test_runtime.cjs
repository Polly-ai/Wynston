#!/usr/bin/env node
'use strict';
// Node-only regression runtime. NEVER prepend this to the production mirror.
const fs = require('node:fs');
const vm = require('node:vm');
function sandbox(body, options = {}) {
  const done = [], logs = [], requests = [], writes = [];
  const store = new Map(Object.entries(options.storage || {}));
  const context = vm.createContext({
    Uint8Array, Uint16Array, Uint32Array, Int8Array, Int16Array, Int32Array,
    Float32Array, Float64Array, ArrayBuffer, DataView,
    $request: {url: options.url || 'https://youtubei.googleapis.com/youtubei/v1/player', method: 'POST', headers: {}},
    $response: {status: 200, headers: {'Content-Type': 'application/x-protobuf'}, body},
    $persistentStore: {
      read(key) { return store.get(key) ?? null; },
      write(value, key) { store.set(key, value); writes.push({key, value}); return true; }
    },
    $notification: {post() {}},
    $httpClient: new Proxy({}, {get(_target, method) {
      return (request, callback) => {
        requests.push({method, url: request.url});
        if (options.httpReply) callback(null, {status: 200, headers: {}}, options.httpReply);
        else callback('network disabled by local audit', {status: 599, headers: {}}, '');
      };
    }}),
    $done(value) { done.push(value); },
    console: {log(...args) { logs.push(args.map(String).join(' ')); }}
  });
  if (Object.hasOwn(options, 'argument')) context.$argument = options.argument;
  return {context, done, logs, requests, writes, store};
}
async function execute(source, body, options = {}) {
  const run = sandbox(body, options);
  let thrown;
  try { vm.runInContext(source, run.context, {timeout: options.timeout || 1500}); }
  catch (error) { thrown = error; }
  // Entry point is async but all mock IO settles immediately. No real timers/IO.
  await new Promise(resolve => setImmediate(resolve));
  return {...run, thrown, result: run.done[0]};
}
function inspect(source) {
  // Audit-only export; never written back to or executed instead of the mirror.
  const marker = 'qr().catch(';
  const offset = source.lastIndexOf(marker);
  if (offset < 0) throw new Error('Audit export marker changed; review upstream before updating tests');
  const run = sandbox(new Uint8Array());
  const instrumented = source.slice(0, offset) +
    'globalThis.__audit={routes:Yr,env:w,unknown:f,getRoute:or};})();';
  vm.runInContext(instrumented, run.context, {timeout: 1500});
  const audit = run.context.__audit;
  if (!audit || audit.routes.size !== 8) throw new Error('Unexpected upstream route map');
  return {...run, ...audit};
}
module.exports = {execute, inspect, sandbox};
if (require.main === module) {
  const file = process.argv[2];
  if (!file) { console.error('Usage: node runtime.cjs <youtube.response.js>'); process.exit(2); }
  const audit = inspect(fs.readFileSync(file, 'utf8'));
  console.log(JSON.stringify({environment: audit.env.className, routes: [...audit.routes.keys()],
    bodyInput: '$response.body: Uint8Array', bodyOutput: '$done({body: Uint8Array})',
    webAPIRequired: false}, null, 2));
}
