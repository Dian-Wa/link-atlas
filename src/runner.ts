import {current,workspace} from './local-accounts';
import {read,write,now,type Row,type State} from './storage';
import {resource} from './backup';
import {networkFetch} from './transport';
import {LOCAL_SERVICE,isLocalService,localServiceReady,bridgeDisconnected} from './local-bridge';
export {networkFetch} from './transport';
let started=false,busy=false;
const owner=crypto.randomUUID();
const configured=String((import.meta as any).env?.VITE_FETCH_SERVICE_URL??'').replace(/\/$/,'');
export function serviceUrl(s:State){return s.meta[0]?.service_url||configured||LOCAL_SERVICE;}
function classify(s:State,r:Row,result:any){const text=[r.url,result.title,result.description,JSON.stringify(result.repo??{})].join(' ').toLowerCase();for(const rule of s.rules.filter(x=>!x.deleted).slice().reverse()){const cat=s.categories.find(x=>x.id===rule.category_id&&!x.deleted&&x.library_id===r.library_id);if(!cat)continue;for(const word of rule.keywords.split(/[,，]/).map((x:string)=>x.trim().toLowerCase()).filter(Boolean)){const matches=/^[a-z0-9]+$/.test(word)?new RegExp('(^|[^a-z0-9])'+word+'([^a-z0-9]|$)').test(text):text.includes(word);if(matches)return {category_id:cat.id,classification_reason:'匹配本地分类规则：'+word};}}return {classification_reason:'没有匹配规则，已放入待整理'};}
async function execute(name:string,task:Row,endpoint:string,limit:number){
 let payload:any,status='failed',message='',delay:number|undefined,unavailable=false;
 try{
  const response=await networkFetch(endpoint.replace(/\/$/,'')+'/fetch-api/fetch',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({url:task.url,page_limit_mib:limit}),signal:AbortSignal.timeout(50000),referrerPolicy:'no-referrer'});
  const data=await response.json();if(response.status===429){delay=Math.max(1,Math.min(86400,Number(response.headers.get('Retry-After')??data.retry_after)||60));message=data.detail||'服务限流，等待重试';}
  else if(response.ok){payload=data.data;status=data.status;message=data.message;if(!['success','partial','failed'].includes(status)||!payload||typeof payload!=='object'||Array.isArray(payload)||typeof message!=='string')throw Error('抓取服务返回格式无效');resource({...payload,url:task.url,status},1);}
  else {message=data.detail||'抓取服务请求失败';if(data.retryable&&task.attempts<2)delay=2**(task.attempts+1);}
 }catch(error){payload=undefined;status='failed';if(isLocalService(endpoint)){unavailable=true;delay=5;message='本机抓取连接已断开，等待服务恢复；未消耗网页重试次数';bridgeDisconnected(endpoint);}else{message='网络请求失败：'+(error as Error).message;if(task.attempts<2)delay=2**(task.attempts+1);}}
 await write(name,(s,put)=>{
  const t=s.tasks.find(x=>x.id===task.id&&!x.deleted),r=s.resources.find(x=>x.id===task.resource_id&&!x.deleted);if(!t||!r||t.owner!==owner)return;
  const updates:any={};if(payload){const values={...payload,...classify(s,r,payload)};for(const key of ['title','description','repo','tags','kind','category_id','classification_reason'])if(values[key]!==undefined&&!r.manual_fields.includes(key))updates[key]=values[key];}
  const finalStatus=delay?'queued':status;put('tasks',{...t,status:finalStatus,attempts:t.attempts+(unavailable?0:1),next_run:delay?Date.now()/1000+delay:0,message:message.slice(0,1000),updated_at:now(),owner:null});put('resources',{...r,...updates,status:finalStatus,fetch_message:message.slice(0,1000),updated_at:now()});
 });
}
async function tick(){if(busy||!navigator.onLine||!navigator.locks)return;busy=true;try{const user=await current();if(!user)return;const name=workspace(user.id),s=await read(name),endpoint=serviceUrl(s);if(!endpoint||!s.tasks.some(x=>!x.deleted&&(x.status==='running'&&x.owner!==owner||x.status==='queued'&&x.next_run<=Date.now()/1000)))return;
 if(!await localServiceReady(endpoint))return;
 await navigator.locks.request('atlas-crawler-'+name,{ifAvailable:true},async lock=>{if(!lock)return;const tasks=await write(name,(s,put)=>{for(const t of s.tasks.filter(x=>!x.deleted&&x.status==='running'&&x.owner!==owner)){put('tasks',{...t,status:'queued',owner:null,message:'页面重新打开，恢复排队'});const r=s.resources.find(x=>x.id===t.resource_id);if(r)put('resources',{...r,status:'queued'});}const due=s.tasks.filter(x=>!x.deleted&&x.status==='queued'&&x.next_run<=Date.now()/1000).sort((a,b)=>a.id-b.id).slice(0,3);return due.map(t=>{put('tasks',{...t,status:'running',owner,updated_at:now()});const r=s.resources.find(x=>x.id===t.resource_id&&!x.deleted)!;put('resources',{...r,status:'running'});return {...t,url:r.url};});});await Promise.allSettled(tasks.map(t=>execute(name,t,endpoint,s.meta[0].page_limit_mib)));});
 }catch(error){window.dispatchEvent(new CustomEvent('atlas-storage-error',{detail:(error as Error).message}));}finally{busy=false;}}
export function startRunner(){if(started)return;started=true;setInterval(()=>void tick(),1000);window.addEventListener('online',()=>void tick());void tick();}
