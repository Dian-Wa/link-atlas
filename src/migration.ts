import {read,write,tables,canonical,destination,text,type State,type Row} from './storage';
import {workspace,migrationIdentity,migrationConflict,reserveMigration,activateMigration,type User} from './local-accounts';
import {exportData,importData,resource} from './backup';
import {backupDigest} from './backup-safety';
const FORMAT='link-atlas-account-migration',ITERATIONS=600000,MAX=32*1024*1024;
const aad=new TextEncoder().encode('LinkAtlasMigration:v1:PBKDF2-SHA256:AES-256-GCM');
const statuses=['queued','running','paused','canceled','success','partial','failed'];
function secret(value:unknown):string{if(typeof value!=='string'||value.length<8||value.length>128)throw Error('请输入 8–128 位原账号密码');return value;}
function base64(bytes:Uint8Array){const chunks=[];for(let i=0;i<bytes.length;i+=32768)chunks.push(String.fromCharCode(...bytes.subarray(i,i+32768)));return btoa(chunks.join(''));}
function bytes(value:unknown,max:number){if(typeof value!=='string'||value.length>max||!value.length||value.length%4||!/^[A-Za-z0-9+/]*={0,2}$/.test(value))throw Error('迁移包编码无效');const raw=atob(value),result=new Uint8Array(raw.length);for(let i=0;i<raw.length;i++)result[i]=raw.charCodeAt(i);return result;}
async function key(password:string,salt:Uint8Array){const material=await crypto.subtle.importKey('raw',new TextEncoder().encode(password),'PBKDF2',false,['deriveKey']);return crypto.subtle.deriveKey({name:'PBKDF2',hash:'SHA-256',salt:salt as BufferSource,iterations:ITERATIONS},material,{name:'AES-GCM',length:256},false,['encrypt','decrypt']);}
function empty():State{return {resources:[],tasks:[],libraries:[],categories:[],rules:[],shortcuts:[],meta:[],trash:[]};}
function validId(value:unknown){if(!Number.isSafeInteger(value)||Number(value)<1)throw Error('迁移包记录 ID 无效');}
function task(row:Row){validId(row.id);validId(row.resource_id);if(!statuses.includes(row.status)||!Number.isInteger(row.attempts)||row.attempts<0||row.attempts>100000||!Number.isFinite(row.next_run)||row.next_run<0)throw Error('迁移包任务格式无效');if(row.message!==undefined&&(typeof row.message!=='string'||row.message.length>4000))throw Error('迁移包任务说明无效');}
async function validate(payload:any){
 if(!payload||typeof payload!=='object'||payload.version!==1||typeof payload.migration_id!=='string'||!/^[a-f0-9-]{36}$/.test(payload.migration_id))throw Error('迁移包内容格式无效');
 const user=payload.profile;
 if(!user||typeof user.username!=='string'||user.username!==user.username.normalize('NFKC').toLowerCase()||!/^[\p{L}\p{N}_.-]{2,32}$/u.test(user.username))throw Error('迁移包账号名称无效');
 text(user.workspace_name,40);if(typeof user.avatar!=='string'||user.avatar.length>2800000||user.avatar&&!/^data:image\/(png|jpeg|webp);base64,/.test(user.avatar))throw Error('迁移包头像格式无效');
 if(user.avatar){const img=new Image();img.src=user.avatar;await img.decode();if(img.width*img.height>4000000)throw Error('迁移包头像过大');}
 const state=payload.state as State;
 if(!state||tables.some(table=>!Array.isArray(state[table])||state[table].length>250000))throw Error('迁移包资料列表格式无效');
 for(const table of tables){const ids=new Set();for(const row of state[table]){if(!row||typeof row!=='object'||Array.isArray(row))throw Error('迁移包记录格式无效');validId(row.id);if(ids.has(row.id))throw Error('迁移包含重复 ID');ids.add(row.id);}}
 if(state.resources.filter(r=>!r.deleted).length>100000)throw Error('迁移包超过 100000 条链接');
 const meta=state.meta[0];if(state.meta.length!==1||meta.id!==1||!Number.isInteger(meta.page_limit_mib)||meta.page_limit_mib<1||meta.page_limit_mib>10)throw Error('迁移包设置无效');
 for(const field of ['data_revision','backup_revision','trash_sequence'])if(meta[field]!==undefined&&(!Number.isSafeInteger(meta[field])||meta[field]<0))throw Error('迁移包备份版本无效');
 if(meta.service_url!==undefined&&typeof meta.service_url!=='string')throw Error('迁移包抓取地址无效');
 for(const row of state.categories.filter(r=>!r.deleted)){if(!state.libraries.some(l=>!l.deleted&&l.id===row.library_id))throw Error('迁移包分类对应的资源库不存在');if(row.parent_id!=null&&!state.categories.some(c=>!c.deleted&&c.id===row.parent_id&&c.library_id===row.library_id))throw Error('迁移包父分类不存在');}
 if(meta.service_url){const url=new URL(meta.service_url);if(url.protocol!=='https:'&&!(url.protocol==='http:'&&['localhost','127.0.0.1'].includes(url.hostname))||url.username||url.password||url.hash||url.search||url.pathname!=='/')throw Error('迁移包抓取地址无效');}
 for(const row of state.resources)if(!row.deleted||row.url){resource(row,row.id);if(!row.deleted)destination(state,row.library_id,row.category_id);}
 for(const row of state.tasks)if(!row.deleted){task(row);if(!state.resources.some(r=>r.id===row.resource_id&&!r.deleted))throw Error('迁移包任务对应的链接不存在');}
 for(const row of state.trash){if(!['resources','tasks'].includes(row.kind)||!row.data?.row||typeof row.name!=='string'||typeof row.removed_at!=='string')throw Error('迁移包回收区无效');if(row.kind==='resources'){validId(row.data.row.id);resource(row.data.row,row.data.row.id);if(!Array.isArray(row.data.tasks??[]))throw Error('迁移包回收任务无效');for(const t of row.data.tasks??[])task(t);}else task(row.data.row);if(row.data.resource_url)canonical(row.data.resource_url);}
 // Reuse normal import validation for live navigation relationships, cycles and rules.
 const probe=empty();importData(probe,(table,row)=>{const i=probe[table].findIndex(r=>r.id===row.id);if(i<0)probe[table].push(row);else probe[table][i]=row;},exportData(state));
 return {profile:{username:user.username,workspace_name:user.workspace_name,avatar:user.avatar} as Omit<User,'id'>,state,migration_id:payload.migration_id};
}
async function unlock(archive:any,password:unknown){
 const pass=secret(password);if(!archive||archive.format!==FORMAT||archive.version!==1||archive.kdf!=='PBKDF2-SHA256'||archive.iterations!==ITERATIONS||archive.cipher!=='AES-256-GCM')throw Error('请选择账号与资料迁移包；普通 JSON 请登录后在导入/导出中恢复');
 const salt=bytes(archive.salt,64),iv=bytes(archive.iv,32),ciphertext=bytes(archive.ciphertext,Math.ceil((MAX+16)/3)*4);
 if(salt.length!==24||iv.length!==12||ciphertext.length>MAX+16)throw Error('迁移包大小或加密参数无效');
 let raw:ArrayBuffer;try{raw=await crypto.subtle.decrypt({name:'AES-GCM',iv:iv as BufferSource,additionalData:aad},await key(pass,salt),ciphertext as BufferSource);}catch{throw Error('原账号密码错误或迁移包已损坏；未写入资料');}
 const payload=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(raw));return {...await validate(payload),digest:await backupDigest(archive),password:pass};
}
function cleanSnapshot(state:State){const result=structuredClone(state);for(const t of result.tasks){delete t.owner;delete t.lease;delete t.run_id;if(t.status==='running'){t.status='queued';t.message='从迁移包恢复，等待抓取';}}for(const r of result.resources)if(r.status==='running')r.status='queued';return result;}
export async function migrationRoute(path:string,data:any){
 if(path==='/export'){
  const user=await migrationIdentity(data.password,data.account_id),state=cleanSnapshot(await read(workspace(user.id)));
  const payload={version:1,migration_id:crypto.randomUUID(),exported_at:new Date().toISOString(),profile:{username:user.username,workspace_name:user.workspace_name,avatar:user.avatar},state};
  const plaintext=new TextEncoder().encode(JSON.stringify(payload));if(plaintext.length>MAX||state.resources.filter(r=>!r.deleted).length>100000)throw Error('迁移资料超过 32 MiB / 100000 条，资料仍保留；请先使用普通备份并联系维护者');
  await validate(payload);
  const salt=crypto.getRandomValues(new Uint8Array(24)),iv=crypto.getRandomValues(new Uint8Array(12)),encrypted=await crypto.subtle.encrypt({name:'AES-GCM',iv,additionalData:aad},await key(secret(data.password),salt),plaintext);
  return {archive:{format:FORMAT,version:1,kdf:'PBKDF2-SHA256',iterations:ITERATIONS,cipher:'AES-256-GCM',salt:base64(salt),iv:base64(iv),ciphertext:base64(new Uint8Array(encrypted))},revision:state.meta[0]?.data_revision??0};
 }
 if(path!=='/preview'&&path!=='/restore')throw Error('不支持的迁移操作');
 const value=await unlock(data.archive,data.password),conflict=await migrationConflict(value.profile.username,value.digest);
 const counts=Object.fromEntries(tables.filter(t=>t!=='meta').map(table=>[table,table==='trash'?value.state[table].length:value.state[table].filter(r=>!r.deleted).length]));
 if(path==='/preview')return {username:value.profile.username,workspace_name:value.profile.workspace_name,counts,conflict,digest:value.digest};
 if(data.confirmed!==true||data.preview_digest!==value.digest)throw Error('请先预览并确认迁移包');
 if(conflict)throw Error('当前浏览器已有同名账号，不能覆盖；请使用其他浏览器或独立浏览器配置文件迁移');
 return navigator.locks.request('atlas-account-migration',async()=>{
  const id=await reserveMigration(value.profile,value.password,value.digest);
  try{
   await write(workspace(id),(s,put)=>{if(tables.some(table=>s[table].length)){
    // Only a previously staged workspace for this same inactive migration may exist.
    if(s.meta[0]?.migration_id!==value.digest)throw Error('目标空间已有资料，迁移已停止');
   }
   for(const table of tables)for(const row of value.state[table])put(table,row);
   const meta=value.state.meta[0];put('meta',{...meta,migration_id:value.digest,last_backup:new Date().toISOString(),backup_revision:meta.data_revision??0});
   });
   const user=await activateMigration(id,value.digest);return {username:user.username,workspace_name:user.workspace_name,counts,restored:true};
  }catch{throw Error('迁移未完成，账号尚未激活；请检查浏览器存储空间后使用同一迁移包重试。原有账号不会被覆盖');}
 });
}
