import type {Row} from './storage';
function timestamp(value:unknown){
 if(typeof value!=='string'||!value.trim())return NaN;
 const date=value.trim().replace(' ','T');
 return Date.parse(/(?:Z|[+-]\d{2}:?\d{2})$/i.test(date)?date:date+'Z');
}
export function resourceOrder(sort:string|null){
 const direction=sort==='oldest'?1:-1;
 return (a:Row,b:Row)=>{
  const left=timestamp(a.created_at),right=timestamp(b.created_at);
  if(Number.isNaN(left)!==Number.isNaN(right))return Number.isNaN(left)?1:-1;
  return (Number.isNaN(left)?0:(left-right)*direction)||(a.id-b.id)*direction;
 };
}
