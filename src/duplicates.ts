import {canonical,type Row} from './storage';

// Matching keys only: keep the saved address unchanged. Unknown query parameters,
// schemes, path casing and trailing slashes remain significant on ordinary sites.
const tracking=/^(utm_[a-z0-9_]+|fbclid|gclid|dclid|msclkid|igshid)$/i;
export function duplicateKey(value:unknown){
 const url=new URL(canonical(value));
 const parts=url.search.slice(1).split('&');
 if(parts.some(part=>tracking.test(new URLSearchParams(part).keys().next().value??'')))url.search=parts.filter(part=>!tracking.test(new URLSearchParams(part).keys().next().value??'')).join('&');
 if(['github.com','www.github.com'].includes(url.hostname)&&!url.port&&!url.search){
  const match=url.pathname.match(/^\/([^/]+)\/([^/]+?)\/?$/);
  if(match)return 'github-repository:'+match[1].toLowerCase()+'/'+match[2].replace(/\.git$/i,'').toLowerCase();
 }
 return url.href;
}
export function duplicateIndex(rows:Row[]){const index=new Map<string,Row>();for(const row of rows)if(!row.deleted){try{const key=duplicateKey(row.url);if(!index.has(key))index.set(key,row);}catch{}}return index;}
export function duplicateDetail(url:string,existing:Row){
 return {url,existing_id:existing.id,existing_url:existing.url,title:existing.title||existing.url,archived:!!existing.archived,reason:canonical(url)===canonical(existing.url)?'相同地址（忽略普通页面锚点，保留路由片段）':duplicateKey(url).startsWith('github-repository:')?'同一 GitHub 仓库（大小写、.git 或末尾斜杠变体）':'忽略常见追踪参数后地址相同'};
}
