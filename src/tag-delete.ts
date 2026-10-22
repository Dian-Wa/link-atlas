import {type State,type Row,now} from './storage';
const has=(r:any,name:string)=>Array.isArray(r?.tags)&&r.tags.includes(name);
export function tagPreview(s:State,value:unknown){
 if(typeof value!=='string'||value.length>60)throw Error('标签名称无效');
 const name=value,rows=s.resources.filter(r=>has(r,name)),trash=s.trash.filter(t=>has(t.data?.row,name));
 return {name,active:rows.filter(r=>!r.deleted&&!r.archived).length,archived:rows.filter(r=>!r.deleted&&r.archived).length,trash:trash.length,revision:s.meta[0].data_revision??0,exists:rows.length>0||trash.length>0};
}
export function deleteTag(s:State,put:(table:any,row:Row)=>void,data:any){
 const p=tagPreview(s,data.name);
 if(data.confirmed!==true)throw Error('请先确认删除标签及关联影响');
 if(data.expected_revision!==p.revision)throw Error('资料已有变化，请重新打开删除确认，核对关联数量后再操作');
 if(!p.exists)throw Error('标签已不存在，请刷新列表');
 // Recovery records are references too: block rather than alter their contents.
 if(p.trash)throw Error('该标签仍被 '+p.trash+' 条回收记录引用。请先恢复相关链接，或在回收区彻底删除相关记录，再删除标签');
 const stamp=now();
 for(const r of s.resources.filter(r=>has(r,p.name)))put('resources',{...r,tags:r.tags.filter((t:string)=>t!==p.name),updated_at:stamp,manual_fields:[...new Set([...(r.manual_fields??[]),'tags'])]});
 return {deleted:true,name:p.name,affected:p.active+p.archived};
}
