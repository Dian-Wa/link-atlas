import {destination,now,type State,type Row,type Table} from './storage';
import {resource} from './backup';
export function bulkEdit(s:State,put:(table:Table,row:Row)=>void,data:any){
 if(!Array.isArray(data.ids)||!data.ids.length||data.ids.length>500||new Set(data.ids).size!==data.ids.length||data.ids.some((x:any)=>!Number.isSafeInteger(x)||x<1))throw Error('请选择 1–500 条不重复的资源');
 if(!['move','tags_add','tags_remove','archive','restore'].includes(data.action))throw Error('批量操作无效');
 const rows=data.ids.map((id:number)=>{const r=s.resources.find(x=>x.id===id&&!x.deleted);if(!r)throw Error('部分资源已不存在，请刷新后重新选择；未修改任何资源');return r;});
 const dest=data.action==='move'?destination(s,data.library_id??null,data.category_id??null):null;
 let tags:string[]=[];if(data.action.startsWith('tags_')){if(!Array.isArray(data.tags)||!data.tags.length||data.tags.some((x:unknown)=>typeof x!=='string'||!x.trim()||x.trim().length>60))throw Error('请输入有效标签，每个最多 60 字');tags=[...new Set(data.tags.map((x:string)=>x.trim()))] as string[];if(tags.length>30)throw Error('每次最多 30 个标签');}
 // Prepare and validate every row before writing any record; storage also rolls back on errors.
 const updates=rows.map((r:Row)=>{const changes:any={},fields=new Set<string>(r.manual_fields);
  if(dest){Object.assign(changes,dest);fields.add('library_id');fields.add('category_id');}
  if(data.action==='tags_add'){changes.tags=[...new Set([...r.tags,...tags])];fields.add('tags');}
  if(data.action==='tags_remove'){changes.tags=r.tags.filter((t:string)=>!tags.includes(t));fields.add('tags');}
  if(data.action==='archive'||data.action==='restore')changes.archived=data.action==='archive'?1:0;
  return {...resource({...r,...changes,manual_fields:[...fields],updated_at:now()},r.id),status:r.status};
 });
 for(const r of updates)put('resources',r);return {updated:updates.length,action:data.action};
}
