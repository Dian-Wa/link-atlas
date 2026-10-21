// IndexedDB records are committed atomically. Writes use Web Locks across tabs.
export type Row={id:number;[key:string]:any};
export const tables=['resources','tasks','libraries','categories','rules','shortcuts','meta','trash'] as const;
export type Table=typeof tables[number];
export type State=Record<Table,Row[]>;
const connections=new Map<string,Promise<IDBDatabase>>();
const snapshots=new Map<string,Promise<State>>();
const channel=typeof BroadcastChannel!=='undefined'?new BroadcastChannel('atlas-browser-changes'):null;
channel?.addEventListener('message',event=>{snapshots.delete(event.data);window.dispatchEvent(new Event('atlas-data-changed'));});
function request<T>(r:IDBRequest<T>):Promise<T>{return new Promise((resolve,reject)=>{r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);});}
export function database(name:string){
 let promise=connections.get(name);if(!promise){promise=new Promise<IDBDatabase>((resolve,reject)=>{const r=indexedDB.open(name,1);r.onupgradeneeded=()=>{for(const table of tables)r.result.createObjectStore(table,{keyPath:'id'});};r.onsuccess=()=>{r.result.onversionchange=()=>r.result.close();resolve(r.result);};r.onerror=()=>reject(Error('浏览器存储不可用，请使用普通浏览窗口并允许本站保存数据'));r.onblocked=()=>reject(Error('数据库升级被其他标签页阻止，请关闭旧标签页后重试'));});connections.set(name,promise);}return promise;
}
async function load(db:IDBDatabase,mode:IDBTransactionMode='readonly'){
 const tx=db.transaction([...tables],mode);const done=new Promise<void>((resolve,reject)=>{tx.oncomplete=()=>resolve();tx.onabort=()=>reject(tx.error||Error('保存失败，浏览器空间可能不足'));tx.onerror=()=>{};});
 const rows=await Promise.all(tables.map(table=>request(tx.objectStore(table).getAll())));
 return {tx,done,state:Object.fromEntries(tables.map((table,i)=>[table,rows[i]])) as State};
}
export async function read(name:string){let value=snapshots.get(name);if(!value){value=(async()=>{const {state,done}=await load(await database(name));await done;return state;})();snapshots.set(name,value);value.catch(()=>snapshots.delete(name));}return value;}
export async function write<T>(name:string,change:(state:State,put:(table:Table,row:Row)=>void,remove:(table:Table,id:number)=>void)=>T):Promise<T>{
 if(!navigator.locks)throw Error('浏览器不支持安全的多标签写入，请使用新版 Chrome、Edge 或 Firefox');
 return navigator.locks.request('atlas-write-'+name,async()=>{
  const {state,tx,done}=await load(await database(name),'readwrite');
  const track=name.startsWith('link-atlas-browser-space-')&&state.meta.some(x=>x.id===1),changed=new Set<string>();
  const fields:Partial<Record<Table,string[]>>={resources:['url','title','description','notes','tags','repo','manual_fields','library_id','category_id','kind','favorite','archived','deleted'],meta:['page_limit_mib','touched'],tasks:['control_version']};
  const meaningful=(table:Table,before:Row|undefined,after:Row|undefined)=>{if(!track)return;const keys=fields[table];if(keys?keys.some(key=>JSON.stringify(before?.[key])!==JSON.stringify(after?.[key])):JSON.stringify(before)!==JSON.stringify(after))changed.add(table+':'+(after?.id??before?.id));};
  const put=(table:Table,row:Row)=>{const i=state[table].findIndex(x=>x.id===row.id);meaningful(table,i<0?undefined:state[table][i],row);if(i<0)state[table].push(row);else state[table][i]=row;tx.objectStore(table).put(row);};
  const remove=(table:Table,id:number)=>{const i=state[table].findIndex(x=>x.id===id);if(i>=0){meaningful(table,state[table][i],undefined);state[table].splice(i,1);}tx.objectStore(table).delete(id);};
  let result:T;try{result=change(state,put,remove);}catch(error){tx.abort();await done.catch(()=>{});throw error;}
  if(changed.size){const meta={...state.meta.find(x=>x.id===1)!,data_revision:(Number(state.meta.find(x=>x.id===1)?.data_revision)||0)+changed.size};tx.objectStore('meta').put(meta);state.meta[state.meta.findIndex(x=>x.id===1)]=meta;}
  await done;snapshots.delete(name);channel?.postMessage(name);window.dispatchEvent(new Event('atlas-data-changed'));return result;
 });
}
export const nextId=(rows:Row[])=>rows.reduce((max,row)=>Math.max(max,row.id),0)+1;
export const nextTrashId=(state:State)=>Math.max(nextId(state.trash),Number(state.meta[0]?.trash_sequence)||1);
export const ordered=(rows:Row[])=>rows.filter(x=>!x.deleted).slice().sort((a,b)=>(a.position??0)-(b.position??0)||a.id-b.id);
export const now=()=>new Date().toISOString();
export function canonical(value:unknown){if(typeof value!=='string'||value.length>4096||/[\u0000-\u0020]/.test(value))throw Error('链接格式无效');const u=new URL(value);if(!['https:','http:'].includes(u.protocol)||u.username||u.password)throw Error('只支持不含账号密码的 HTTP/HTTPS 链接');if(!/^#!?\//.test(u.hash))u.hash='';return u.href;}
export function text(value:unknown,max=60){if(typeof value!=='string'||!value.trim()||value.trim().length>max)throw Error(`请输入 1–${max} 字`);return value.trim();}
export function children(state:State,id:number){const ids=new Set([id]);let changed=true;while(changed){changed=false;for(const c of state.categories)if(!c.deleted&&ids.has(c.parent_id)&&!ids.has(c.id)){ids.add(c.id);changed=true;}}return ids;}
export function destination(state:State,library:unknown,category:unknown){let lid=library==null?null:Number(library),cid=category==null?null:Number(category);if(cid!==null){const c=state.categories.find(x=>x.id===cid&&!x.deleted);if(!c)throw Error('分类不存在');if(lid!==null&&lid!==c.library_id)throw Error('分类不属于所选资源库');lid=c.library_id;}if(lid!==null&&!state.libraries.some(x=>x.id===lid&&!x.deleted))throw Error('资源库不存在');return {library_id:lid,category_id:cid};}
export async function initialize(name:string){await write(name,(s,put)=>{if(s.meta.some(x=>x.id===1))return;put('meta',{id:1,page_limit_mib:2,service_url:'',last_backup:null});put('libraries',{id:1,name:'我的资源库',icon:'library',position:0});['开发工具','AI','学习资料','设计资源','实用网站','其他'].forEach((name,i)=>put('categories',{id:i+1,name,parent_id:null,library_id:1,position:i}));['github,gitlab,代码,开发,工具,typescript,javascript,rust','机器学习,人工智能,大模型,llm,openai,huggingface,ai','教程,课程,学习,文档,docs,tutorial','设计,figma,design,icon'].forEach((keywords,i)=>put('rules',{id:i+1,keywords,category_id:i+1}));['all','inbox','repositories','favorites'].forEach((target_key,i)=>put('shortcuts',{id:i+1,name:['全部链接','待整理','开源项目','我的收藏'][i],target_kind:'system',target_key,position:i}));});}
