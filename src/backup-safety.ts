import {duplicateKey,duplicateIndex} from './duplicates';
import type {Row,State} from './storage';
import {importData} from './backup';
export function backupStatus(s:State,time=Date.now()){
 const meta=s.meta[0]??{},revision=Number(meta.data_revision)||0,backedUp=Number(meta.backup_revision)||0,changes=Math.max(0,revision-backedUp),days=meta.last_backup?Math.max(0,Math.floor((time-Date.parse(meta.last_backup))/86400000)):null;
 const hasData=s.resources.some(r=>!r.deleted)||s.trash.length>0;
 const due=hasData&&(!meta.last_backup||changes>=20||(days??0)>=7);
 return {revision,changes,days,last_backup:meta.last_backup??null,due,reason:!hasData?'暂无需要备份的资料':!meta.last_backup?'尚未生成备份':changes>=20?`已有 ${changes} 项内容变更`:(days??0)>=7?`距上次生成备份已 ${days} 天`:`自上次生成后 ${changes} 项变更`,threshold_changes:20,threshold_days:7};
}
function canonicalJson(value:any):string{
 if(Array.isArray(value))return '['+value.map(x=>canonicalJson(x===undefined?null:x)).join(',')+']';
 if(value&&typeof value==='object')return '{'+Object.keys(value).filter(k=>value[k]!==undefined).sort().map(k=>JSON.stringify(k)+':'+canonicalJson(value[k])).join(',')+'}';
 return JSON.stringify(value);
}
export async function backupDigest(data:any){const {integrity,...body}=data;const bytes=new TextEncoder().encode(canonicalJson(body));const hash=await crypto.subtle.digest('SHA-256',bytes);return Array.from(new Uint8Array(hash)).map(x=>x.toString(16).padStart(2,'0')).join('');}
export function backupCounts(data:any){return Object.fromEntries(['resources','libraries','categories','rules','shortcuts','tasks','trash'].map(key=>[key,Array.isArray(data[key])?data[key].length:0]));}
export async function sealBackup(data:any){return {...data,integrity:{algorithm:'SHA-256',digest:await backupDigest(data),counts:backupCounts(data)}};}
export async function checkBackup(data:any){
 if(!data||typeof data!=='object'||Array.isArray(data))throw Error('备份结构无效');
 if(data.format==='link-atlas-account-migration')throw Error('这是账号与资料迁移包，请在登录页导入；普通 JSON 备份在此处恢复');
 const digest=await backupDigest(data);
 if(data.integrity){if(data.integrity.algorithm!=='SHA-256'||data.integrity.digest!==digest)throw Error('备份完整性校验失败，文件可能已损坏或被修改；未写入资料');const counts=backupCounts(data);if(!data.integrity.counts||Object.keys(counts).some(k=>counts[k]!==data.integrity.counts[k]))throw Error('备份数量校验失败；未写入资料');}
 return {digest,integrity:data.integrity?'verified':'legacy'};
}
export async function importPreview(state:State,data:any){
 const checked=await checkBackup(data),s=structuredClone(state),before=backupCounts({resources:s.resources.filter(x=>!x.deleted),libraries:s.libraries.filter(x=>!x.deleted),categories:s.categories.filter(x=>!x.deleted),tasks:s.tasks.filter(x=>!x.deleted),rules:s.rules.filter(x=>!x.deleted),shortcuts:s.shortcuts.filter(x=>!x.deleted),trash:s.trash});
 const put=(table:keyof State,row:Row)=>{const i=s[table].findIndex(x=>x.id===row.id);if(i<0)s[table].push(row);else s[table][i]=row;};
 const priorLibraries=new Set(state.libraries.filter(x=>!x.deleted).map(x=>x.id)),priorCategories=new Set(state.categories.filter(x=>!x.deleted).map(x=>x.id));
 const result=importData(s,put,data),newLibraries=s.libraries.filter(x=>!x.deleted&&!priorLibraries.has(x.id)).length,newCategories=s.categories.filter(x=>!x.deleted&&!priorCategories.has(x.id)).length,after=backupCounts({resources:s.resources.filter(x=>!x.deleted),libraries:s.libraries.filter(x=>!x.deleted),categories:s.categories.filter(x=>!x.deleted),tasks:s.tasks.filter(x=>!x.deleted)});
 const current=duplicateIndex(state.resources),conflicts=(data.resources??[]).filter((r:any)=>{const row=current.get(duplicateKey(r.url));return row&&['title','description','notes','tags'].some(k=>r[k]!==undefined&&JSON.stringify(r[k])!==JSON.stringify(row[k]));});
 return {...checked,revision:state.meta[0]?.data_revision??0,created:result.created,duplicate_details:result.duplicate_details,duplicates:result.duplicates,total:data.resources.length,conflicts:conflicts.length,conflict_samples:conflicts.slice(0,5).map((r:any)=>({url:r.url,title:r.title??r.url})),new_libraries:newLibraries,new_categories:newCategories,merged_libraries:Math.max(0,(data.libraries?.length??0)-newLibraries),merged_categories:Math.max(0,(data.categories?.length??0)-newCategories),new_tasks:after.tasks-before.tasks,before_resources:before.resources,after_resources:after.resources};
}
