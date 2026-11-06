'use strict';
/* Complete ORIGINAL BaiduPan behavior + native Surge guard fixtures.
   CLI: node test_bdpan_runtime.cjs ads|unlock ORIGINAL ADAPTER JQ_SCRIPT
   Never contacts the network or real storage; does not print response contents.
   Dynamic Function is required by the original obfuscator, so this VM is a
   bounded compatibility test, not a security boundary for hostile JavaScript. */
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const [kind,originalPath,adapterPath,jqPath]=process.argv.slice(2);
assert(['ads','unlock'].includes(kind),'Expected ads or unlock');
const original=fs.readFileSync(originalPath,'utf8'),adapter=fs.readFileSync(adapterPath,'utf8');
assert(adapter.includes(original),'Original bytes must be embedded without modifications');
const programs={original:new vm.Script(original,{filename:'original-'+kind+'.js'}),
  adapter:new vm.Script(adapter,{filename:'surge-'+kind+'.js'})};
if(jqPath) programs.jq=new vm.Script(fs.readFileSync(jqPath,'utf8'),{filename:'jq-equivalent.js'});
const start=Date.now();let runs=0,checks=0;
function eq(a,b,label){assert.deepEqual(a,b,label);checks++;}
function yes(value,label){assert(value,label);checks++;}
// Expose a null-prototype bridge returning only strings; URL objects stay outside.
const urlBridge=Object.setPrototypeOf(function(text,key,value){
 try{const u=new URL(String(text));if(key!==null)u.searchParams.set(String(key),String(value));
 return JSON.stringify({url:u.toString(),entries:[...u.searchParams]});}
 catch(_){return JSON.stringify({error:true});}
},null);
function execute(which,url,body,requestOnly=false){
 if(Date.now()-start>150000)throw Error('Total bounded runtime exceeded');
 const context=vm.createContext({__urlBridge:urlBridge},{codeGeneration:{strings:true,wasm:false}});
 const request={url,method:'GET',headers:{'X-Keep':'unchanged'}};
 const response={status:200,headers:{'Content-Type':'application/json'}};
 if(body!==undefined)response.body=body;
 const init=`globalThis.calls=[];globalThis.effects=[];globalThis.window=globalThis;
 globalThis.$request=${JSON.stringify(request)};
 ${requestOnly?'':`globalThis.$response=${JSON.stringify(response)};`}
 globalThis.$environment={'surge-version':'6.100.0'};
 globalThis.$done=x=>calls.push(x===undefined?{}:x);
 globalThis.console={log(){},warn(){},error(){}};
 globalThis.$persistentStore={read(){effects.push('store');throw Error('No storage');},write(){effects.push('store');throw Error('No storage');}};
 globalThis.$httpClient={get(){effects.push('network');throw Error('No network');},post(){effects.push('network');throw Error('No network');}};
 globalThis.fetch=()=>{effects.push('fetch');throw Error('No fetch');};
 globalThis.setTimeout=()=>{effects.push('timer');throw Error('No timers');};
 globalThis.setInterval=globalThis.setTimeout;
 globalThis.URL=class URL{constructor(text){this._u=String(text);const self=this;
 this.searchParams={get(key){const d=JSON.parse(__urlBridge(self._u,null,null));if(d.error)throw Error('Invalid URL');const e=d.entries.find(x=>x[0]===String(key));return e?e[1]:null;},set(key,value){const d=JSON.parse(__urlBridge(self._u,String(key),String(value)));if(d.error)throw Error('Invalid URL');self._u=d.url;}};}
 toString(){const d=JSON.parse(__urlBridge(this._u,null,null));if(d.error)throw Error('Invalid URL');return d.url;}};`;
 vm.runInContext(init,context,{timeout:2000});
 let error=null;
 try{programs[which].runInContext(context,{timeout:15000});}catch(e){error=e.name;}
 const result=JSON.parse(vm.runInContext('JSON.stringify({calls,effects,request:$request})',context,{timeout:2000}));
 eq(result.effects,[],'No real account/network/storage access');runs++;
 return {...result,error};
}
function good(which,url,object,requestOnly=false){
 const body=typeof object==='string'?object:JSON.stringify(object);
 const result=execute(which,url,body,requestOnly);
 eq(result.error,null,'Successful script execution');eq(result.calls.length,1,'Single completion');
 eq(result.request.headers,{'X-Keep':'unchanged'},'Unrelated request header retained');
 const value=result.calls[0];yes(value&&typeof value==='object'&&!Array.isArray(value),'Surge result object');
 yes(!Object.hasOwn(value,'body')||typeof value.body==='string','String response body');
 return value;
}
function unchanged(url,body){const r=execute('adapter',url,body);eq(r.error,null);eq(r.calls,[{}],'Safe passthrough');}
const afd='https://afd.baidu.com/afd/entry';
const feed='https://pan.baidu.com/feed/cardinfos';
const member='https://pan.baidu.com/rest/2.0/membership/user?method=';
const stream='https://pan.baidu.com/api/streaming';
const task='https://pan.baidu.com/api/taskscore/tasklist';
const fA={errno:0,res:{ad:[{id:1}],splash:{id:2},keep:{v:3}},keep:4};
const eA={errno:0,res:{ad:[],splash:{},keep:{v:3}},keep:4};
const fF={data:{cards:[{source:'ad'},{source:'product',id:1},{source:'recent',id:2},{source:'other'}],keep:3},keep:4};
const eF={data:{cards:[{source:'product',id:1},{source:'recent',id:2}],keep:3},keep:4};
if(kind==='ads'){
 for(const [url,input,expected] of [[afd,fA,eA],[feed,fF,eF]]){
  const raw=good('original',url,input),out=good('adapter',url,input);
  eq(out,raw,'Guard preserves complete original business result');eq(JSON.parse(out.body),expected,'Ad removal keeps unrelated fields');
 }
 for(const which of ['original','adapter'])eq(good(which,member+'gamecenter',{keep:1,data:{benefit_list:[1],benefit_totalnum:2}}),{},'Original gamecenter is a no-op, do not invent a membership rewrite');
 for(const [url,body] of [[afd,'{'],[afd,undefined],[afd,'null'],[afd,'{}'],[feed,'not JSON'],[feed,'{"data":{}}'],[feed,'{"data":{"cards":[null]}}']])unchanged(url,body);
 eq(good('adapter','https://unrelated.invalid/api','invalid'),{},'Unknown URL unchanged');
 const originalRules=original.split('*/',1)[0].split(/\r?\n/).filter(x=>x.startsWith('^'));
 eq(originalRules.length,15,'15 active source URL rules');
 for(const [action,n] of [['reject-200',8],['reject-dict',3],['script-response-body',3],['jsonjq-response-body',1]])
  eq(originalRules.filter(x=>x.includes(' url '+action+' ')||x.endsWith(' url '+action)).length,n,action+' count');
 for(const [input,expected] of [['{"result":{"list":[1],"count":3},"keep":1}',{result:{list:[],count:3},keep:1}],
  ['{}',{result:{list:[]}}],['null',{result:{list:[]}}],['{"result":null}',{result:{list:[]}}]])
  eq(JSON.parse(good('jq',task,input).body),expected,'Exact jq assignment semantics');
 for(const input of ['{','',undefined,'[]','3','{"result":false}','{"result":[]}']){
  const r=execute('jq',task,input);eq(r.error,null);eq(r.calls,[{}],'Invalid jq input safely passes through');
 }
}else{
 const samples=['?app_id=1&type=M3U8_HQ_1080','?app_id=1&type=M3U8_HQ_1080&keep=a%20b',
  '?app_id=1&type=M3U8_HQ_1080&type=OTHER','?app_id=1&type=M3U8_HQ_1080junk'];
 for(const query of samples){
  const raw=good('original',stream+query,undefined,true),out=good('adapter',stream+query,undefined,true);
  const expected=new URL(stream+query);if(/^M3U8.*\d$/.test(expected.searchParams.get('type')))expected.searchParams.set('type','M3U8_AUTO_1080');
  eq(out,raw,'Request rewrite retains original URL semantics');eq(out,{url:expected.toString()},'Original streaming behavior');
 }
 const fixtures=[['plain',{keep:1,data:{keep:2}}],['benefit',{keep:1,data:{keep:2,benefit_list:[],benefit_totalnum:3}}],
  ['product',{keep:1,product_infos:[]}],['identity',{keep:1,identity_icon:{}}],['tips',{keep:1,tips_data_list:[]}],
  ['recommend',{keep:1,recommend_list:[]}],['precedence',{product_infos:[],identity_icon:{},tips_data_list:[],recommend_list:[]}]];
 for(const [label,input] of fixtures){
  const url=member+'query',raw=good('original',url,input),out=good('adapter',url,input);
  eq(out,raw,'Membership shape behavior retained: '+label);const value=JSON.parse(out.body);
  if(label==='plain')eq(value,input);
  if(label==='benefit')eq(value,{keep:1,data:{keep:2}});
  if(label==='recommend')eq(value,{error_code:0});
  if(label==='product'||label==='precedence'){eq(value.product_infos.length,3);eq(value.current_product.detail_cluster,'svip');yes(!Object.hasOwn(value,'keep'),'Original full-object replacement retained');}
  if(label==='identity'){eq(value.vip.status,0);eq(value.vipv2.status,1);eq(value.svip.status,2);}
  if(label==='tips'){eq(value.user_status,2);eq(value.user_type,'svip');eq(value.status_data,'超级会员至：2099-12-31');}
 }
 eq(JSON.parse(good('adapter',member+'gamecenter',{keep:1,data:{benefit_list:[],benefit_totalnum:2,keep:3}}).body),{keep:1,data:{keep:3}},'Overlap uses original membership behavior');
 for(const input of ['{','',undefined,'null'])unchanged(member+'query',input);
 eq(good('adapter','https://unrelated.invalid/','bad'),{},'Unknown URL unchanged');
}
console.log(`PASS ${kind}: ${checks} assertions, ${runs} original/guard/jq VM runs; no network or user storage; SHA256 ${crypto.createHash('sha256').update(original).digest('hex')}`);
