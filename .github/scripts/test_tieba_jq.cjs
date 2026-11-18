const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict'), cp = require('node:child_process');
// Differential checks use jq itself, matching Quantumult X's valid JSON transformations.
const script = fs.readFileSync(process.argv[2], 'utf8');
const config = fs.readFileSync(process.argv[3], 'utf8');
let cases = 0;
const fixtures = [null, {}, {keep:123}, {data:null,keep:7}, {data:{discover_list:[1,2],keep:'inside'},hot_search:[1],keep:42}, {game_center:{x:1},tools:[],vip_banner:'vip',task_list:[1],keep:true}, {duxiaoman:1,namoaixud:2,namoaixud_entry:3,recom_naws_list:4,duxiaoman_entry:5,vip_banner:6,zone_info:[null,{type:'ad'},{type:'common_func',keep:1},{type:'auxiliary_func',keep:2}],keep:'outside'}, {zone_info:{a:{type:'common_func'},b:{type:'ad'},c:null},keep:3}];
for (const line of config.split(/\r?\n/)) {
 const m=line.match(/^(\^\S+)\s+url jsonjq-response-body '(.*)'$/); if(!m) continue;
 let url;
 if(m[1].includes('discover')) url='c/f/search/discover';
 else if(m[1].includes('sidebar')) url='c/f/sidebar/home';
 else if(m[1].includes('profile')) url='c/u/user/profile';
 else if(m[1].includes('forumGuide')) url='c/f/forum/forumGuide';
 else url='mo/q/search/startPage';
 for (const obj of fixtures) {
  const input=JSON.stringify(obj), ref=cp.spawnSync('jq',['-c',m[2]],{input,encoding:'utf8'});
  let result,calls=0;
  vm.runInNewContext(script,{$request:{url:'https://tiebac.baidu.com/'+url},$response:{body:input},$done:x=>{result=x;calls++;}},{timeout:1000});
  assert.equal(calls,1);
  if(ref.status===0) assert.deepStrictEqual(JSON.parse(result.body),JSON.parse(ref.stdout),url+' '+input);
  else assert.deepStrictEqual(Object.keys(result),[],url+' jq error should pass through');
  cases++;
 }
}
console.log('jq differential cases passed: '+cases);
