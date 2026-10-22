import {ChevronDown,ChevronRight} from 'lucide-react';
export default function SectionToggle({title,collapsed,controls,onToggle}:{title:string;collapsed:boolean;controls:string;onToggle:()=>void}){
 return <button type="button" className="sidebar-section-toggle" aria-label={(collapsed?'展开':'折叠')+title+'分区'} aria-expanded={!collapsed} aria-controls={controls} onClick={onToggle}>{collapsed?<ChevronRight size={13}/>:<ChevronDown size={13}/>}<span>{title}</span></button>;
}
