const fs = require('fs'), vm = require('vm'), assert = require('assert');
const code = fs.readFileSync(process.argv[2], 'utf8');
let checks = 0;
function run(path, input) {
 let result, calls = 0;
 vm.runInNewContext(code, {$request:{url:'https://tiebac.baidu.com/'+path},$response:{body:input},$done:x=>{result=x; calls++;}}, {timeout:1000});
 assert.equal(calls,1); checks++;
 return result.body === undefined ? null : JSON.parse(result.body);
}
let o=run('c/f/search/discover', JSON.stringify({data:{discover_list:[1],keep:2},keep:3}));
assert.deepStrictEqual(o,{data:{discover_list:[],keep:2},keep:3});checks++;
assert.deepStrictEqual(run('c/f/search/discover','null'),{data:{discover_list:[]}});checks++;
o=run('c/f/sidebar/home',JSON.stringify({game_center:1,tools:2,vip_banner:3,task_list:4,keep:5}));
assert.deepStrictEqual(o,{keep:5});checks++;
o=run('c/u/user/profile',JSON.stringify({duxiaoman:1,namoaixud:2,namoaixud_entry:3,recom_naws_list:4,duxiaoman_entry:5,vip_banner:6,keep:7,zone_info:[{type:'common_func',id:1},{type:'ad'},{type:'auxiliary_func',id:2}]}));
assert.deepStrictEqual(o,{keep:7,zone_info:[{type:'common_func',id:1},{type:'auxiliary_func',id:2}]});checks++;
assert.deepStrictEqual(run('c/f/forum/forumGuide','{"hot_search":[1],"keep":2}'),{hot_search:[],keep:2});checks++;
assert.deepStrictEqual(run('mo/q/search/startPage','{"data":{"ad":1},"keep":2}'),{keep:2});checks++;
for(const bad of ['','not JSON','<html>error</html>','[]','1']) {
 assert.equal(run('c/f/search/discover',bad),null);checks++;
}
assert.equal(run('c/u/user/profile','{"zone_info":null}'),null);checks++;
assert.equal(run('c/f/search/discover','{"data":1}'),null);checks++;
assert.equal(run('unmatched','{"keep":1}'),null);checks++;
console.log('JSON behavioral checks passed: '+checks);
