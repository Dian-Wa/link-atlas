export type DuplicateMatch={url:string;existing_id:number;existing_url:string;title:string;archived:boolean;reason:string};
export default function DuplicateMatches({items}:{items?:DuplicateMatch[]}){
 if(!items?.length)return null;
 return <details className="duplicate-matches" open><summary>重复链接匹配依据（最多显示 20 条）</summary>{items.map((item,i)=><div key={i}><small>{item.url}</small><p>{item.reason}{item.archived?' · 已有资源位于归档中':''}</p><a href={item.existing_url} target="_blank" rel="noopener noreferrer">已保留：{item.title}</a></div>)}<p>保留已有分类、标签、备注及人工内容，不自动合并或覆盖。</p></details>;
}
