"""Persistent library/folder navigation. Removing navigation never deletes links."""
import json

LIBRARY_ICONS={'library','folder','code','globe','book','briefcase','palette','sparkles','heart','star','layers','graduation'}
SYSTEM_SHORTCUTS=[('all','全部链接'),('inbox','待整理'),('repositories','开源项目'),('favorites','我的收藏')]


def valid_icon(value):
    if not isinstance(value,str) or value not in LIBRARY_ICONS:raise ValueError('请选择有效的内置图标')
    return value


def valid_name(value):
    if not isinstance(value,str) or not value.strip() or len(value.strip())>60:
        raise ValueError('名称需要 1–60 字')
    return value.strip()


def descendants(db,cid):
    return [r[0] for r in db.execute('WITH RECURSIVE tree(id) AS (SELECT id FROM categories WHERE id=? AND deleted=0 UNION ALL SELECT c.id FROM categories c JOIN tree t ON c.parent_id=t.id WHERE c.deleted=0) SELECT id FROM tree',(cid,))]


class NavigationStore:
    def migrate_navigation(self,db):
        db.execute('CREATE TABLE IF NOT EXISTS libraries(id INTEGER PRIMARY KEY,name TEXT NOT NULL,position INTEGER NOT NULL DEFAULT 0,deleted INTEGER NOT NULL DEFAULT 0)')
        if not db.execute('SELECT 1 FROM libraries LIMIT 1').fetchone():
            db.execute("INSERT INTO libraries(id,name) VALUES(1,'我的资源库')")
        if 'icon' not in {r['name'] for r in db.execute('PRAGMA table_info(libraries)')}:
            db.execute("ALTER TABLE libraries ADD COLUMN icon TEXT NOT NULL DEFAULT 'library'")
        db.execute('CREATE TABLE IF NOT EXISTS shortcuts(id INTEGER PRIMARY KEY,name TEXT NOT NULL,target_kind TEXT NOT NULL,target_key TEXT NOT NULL,position INTEGER NOT NULL DEFAULT 0,deleted INTEGER NOT NULL DEFAULT 0)')
        if not db.execute('SELECT 1 FROM shortcuts LIMIT 1').fetchone():
            db.executemany("INSERT INTO shortcuts(name,target_kind,target_key,position) VALUES(?,'system',?,?)",[(name,key,i) for i,(key,name) in enumerate(SYSTEM_SHORTCUTS)])
        for table in ('resources','categories'):
            columns={r['name'] for r in db.execute(f'PRAGMA table_info({table})')}
            if 'library_id' not in columns:
                db.execute(f'ALTER TABLE {table} ADD COLUMN library_id INTEGER REFERENCES libraries(id)')
                db.execute(f'UPDATE {table} SET library_id=1')
            if table=='categories':
                for column in ('position','deleted'):
                    if column not in columns:
                        db.execute(f'ALTER TABLE categories ADD COLUMN {column} INTEGER NOT NULL DEFAULT 0')
                        if column=='position':db.execute('UPDATE categories SET position=id')
        db.execute('CREATE INDEX IF NOT EXISTS resource_library ON resources(library_id,archived)')

    def libraries(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT l.*,COUNT(r.id) count FROM libraries l LEFT JOIN resources r ON r.library_id=l.id AND r.archived=0 WHERE l.deleted=0 GROUP BY l.id ORDER BY l.position,l.id')]

    def save_library(self,data,lid=None):
        with self.lock,self.connect() as db:
            current=db.execute('SELECT * FROM libraries WHERE id=? AND deleted=0',(lid,)).fetchone() if lid else None
            if lid and not current:raise ValueError('资源库不存在')
            name=valid_name(data.get('name',current['name'] if current else None))
            icon=valid_icon(data.get('icon',current['icon'] if current else 'library'))
            if db.execute('SELECT 1 FROM libraries WHERE name=? AND deleted=0 AND id!=?',(name,lid or -1)).fetchone():
                raise ValueError('资源库名称已存在')
            if lid:
                if not db.execute('SELECT 1 FROM libraries WHERE id=? AND deleted=0',(lid,)).fetchone():raise ValueError('资源库不存在')
                db.execute('UPDATE libraries SET name=?,icon=? WHERE id=?',(name,icon,lid))
            else:
                lid=db.execute('INSERT INTO libraries(name,icon,position) VALUES(?,?,(SELECT COALESCE(MAX(position),0)+1 FROM libraries))',(name,icon)).lastrowid
            return dict(db.execute('SELECT * FROM libraries WHERE id=?',(lid,)).fetchone())

    def default_library(self,db):
        row=db.execute('SELECT id FROM libraries WHERE deleted=0 ORDER BY position,id LIMIT 1').fetchone()
        return row['id'] if row else None

    def folder_library(self,db,lid,cid=None):
        if lid is not None and (type(lid) is not int or lid<=0):raise ValueError('无效的资源库编号')
        if cid is not None and (type(cid) is not int or cid<=0):raise ValueError('无效的文件夹编号')
        if cid is not None:
            folder=db.execute('SELECT * FROM categories WHERE id=? AND deleted=0',(cid,)).fetchone()
            if not folder:raise ValueError('文件夹不存在')
            if lid is not None and lid!=folder['library_id']:raise ValueError('文件夹不属于所选资源库')
            lid=folder['library_id']
        if lid is not None and not db.execute('SELECT 1 FROM libraries WHERE id=? AND deleted=0',(lid,)).fetchone():
            raise ValueError('资源库不存在')
        return lid

    def save_category(self,data,cid=None):
        name=valid_name(data.get('name'))
        with self.lock,self.connect() as db:
            current=db.execute('SELECT * FROM categories WHERE id=? AND deleted=0',(cid,)).fetchone() if cid else None
            if cid and not current:raise ValueError('文件夹不存在')
            parent=data.get('parent_id',current['parent_id'] if current else None) or None
            lid=data.get('library_id',current['library_id'] if current else None)
            if parent:
                lid=self.folder_library(db,lid,parent)
                if cid and parent in descendants(db,cid):raise ValueError('不能将文件夹移动到自身或其子文件夹内')
            if lid is None:lid=self.default_library(db)
            if lid is None:raise ValueError('请先创建资源库')
            self.folder_library(db,lid)
            if current and lid!=current['library_id']:raise ValueError('文件夹不能跨资源库移动，请移动其中的资源')
            if db.execute('SELECT 1 FROM categories WHERE name=? AND parent_id IS ? AND library_id=? AND deleted=0 AND id!=?',(name,parent,lid,cid or -1)).fetchone():
                raise ValueError('同一文件夹内名称已存在')
            if cid:
                db.execute('UPDATE categories SET name=?,parent_id=? WHERE id=?',(name,parent,cid))
            else:
                cid=db.execute('INSERT INTO categories(name,parent_id,library_id,position) VALUES(?,?,?,(SELECT COALESCE(MAX(position),0)+1 FROM categories WHERE library_id=? AND parent_id IS ?))',(name,parent,lid,lid,parent)).lastrowid
            return dict(db.execute('SELECT * FROM categories WHERE id=?',(cid,)).fetchone())

    def reorder_navigation(self,data):
        kind=data.get('kind')
        ids=data.get('ids')
        if not isinstance(ids,list) or any(type(i) is not int for i in ids) or len(ids)!=len(set(ids)):
            raise ValueError('排序列表无效')
        with self.lock,self.connect() as db:
            if kind=='library':
                table='libraries';rows=db.execute('SELECT id FROM libraries WHERE deleted=0').fetchall()
            elif kind=='shortcut':
                table='shortcuts';rows=db.execute('SELECT id FROM shortcuts WHERE deleted=0').fetchall()
            elif kind=='folder':
                table='categories';rows=db.execute('SELECT id FROM categories WHERE library_id=? AND parent_id IS ? AND deleted=0',(data.get('library_id'),data.get('parent_id'))).fetchall()
            else:raise ValueError('无效节点类型')
            if set(ids)!={r['id'] for r in rows}:raise ValueError('只能对同级节点排序，请刷新后重试')
            db.executemany(f'UPDATE {table} SET position=? WHERE id=?',[(p,i) for p,i in enumerate(ids)])
        return {'saved':True}

    def navigation_preview(self,kind,nid):
        with self.connect() as db:
            return self._navigation_preview(db,kind,nid)

    def _navigation_preview(self,db,kind,nid):
        if kind=='library':
            row=db.execute('SELECT * FROM libraries WHERE id=? AND deleted=0',(nid,)).fetchone()
            if not row:raise ValueError('资源库不存在')
            folder_ids=[r[0] for r in db.execute('SELECT id FROM categories WHERE library_id=? AND deleted=0',(nid,))]
            total=db.execute('SELECT COUNT(*) FROM resources WHERE library_id=?',(nid,)).fetchone()[0]
        elif kind=='folder':
            row=db.execute('SELECT * FROM categories WHERE id=? AND deleted=0',(nid,)).fetchone()
            if not row:raise ValueError('文件夹不存在')
            folder_ids=descendants(db,nid)
            total=db.execute('SELECT COUNT(*) FROM resources WHERE category_id IN ('+','.join('?' for _ in folder_ids)+')',folder_ids).fetchone()[0]
        else:raise ValueError('无效节点类型')
        return {'name':row['name'],'resources':total,'folders':len(folder_ids),'folder_ids':folder_ids}

    def remove_navigation(self,kind,nid,confirmed=False):
        if confirmed is not True:raise ValueError('请确认移除导航节点；其中的链接将保留')
        with self.lock,self.connect() as db:
            preview=self._navigation_preview(db,kind,nid)
            ids=preview['folder_ids']
            if kind=='library':
                rows=db.execute('SELECT id,manual_fields FROM resources WHERE library_id=?',(nid,)).fetchall()
                db.execute('UPDATE libraries SET deleted=1 WHERE id=?',(nid,))
            else:
                rows=db.execute('SELECT id,manual_fields FROM resources WHERE category_id IN ('+','.join('?' for _ in ids)+')',ids).fetchall()
            for row in rows:
                fields=set(json.loads(row['manual_fields']))|{'category_id'}
                if kind=='library':fields.add('library_id')
                db.execute('UPDATE resources SET category_id=NULL'+(',library_id=NULL' if kind=='library' else '')+',manual_fields=? WHERE id=?',(json.dumps(sorted(fields)),row['id']))
            # Keep tombstones for referential integrity, release names for new folders.
            db.executemany("UPDATE categories SET deleted=1,name=name||' [已移除:'||id||']' WHERE id=?",[(i,) for i in ids])
            if kind=='library':db.execute("UPDATE shortcuts SET deleted=1 WHERE target_kind='library' AND target_key=?",(str(nid),))
            db.executemany("UPDATE shortcuts SET deleted=1 WHERE target_kind='folder' AND target_key=?",[(str(i),) for i in ids])
        return {'removed':True,'preserved_resources':preview['resources']}

    def shortcut_target(self,db,kind,target):
        if kind=='system':
            if target not in dict(SYSTEM_SHORTCUTS):raise ValueError('无效的快捷入口目标')
            return {'view':target,'library_id':None,'category_id':None,'icon':{'all':'layers','inbox':'folder','repositories':'code','favorites':'star'}[target]}
        try:nid=int(target)
        except (ValueError,TypeError):raise ValueError('无效的快捷入口目标')
        if kind=='library':
            self.folder_library(db,nid)
            row=db.execute('SELECT icon FROM libraries WHERE id=?',(nid,)).fetchone()
            return {'view':'all','library_id':nid,'category_id':None,'icon':row['icon']}
        if kind=='folder':
            lid=self.folder_library(db,None,nid)
            return {'view':'all','library_id':lid,'category_id':nid,'icon':'folder'}
        raise ValueError('请选择资源库、文件夹或系统入口')

    def shortcuts(self):
        with self.connect() as db:
            rows=[dict(r) for r in db.execute('SELECT * FROM shortcuts WHERE deleted=0 ORDER BY position,id')]
            result=[]
            for row in rows:
                try:target=self.shortcut_target(db,row['target_kind'],row['target_key'])
                except ValueError:continue
                clauses=['archived=0'];args=[]
                if kind:=target.get('category_id'):
                    ids=descendants(db,kind)
                    clauses.append('category_id IN ('+','.join('?' for _ in ids)+')');args.extend(ids)
                if target['library_id'] is not None:clauses.append('library_id=?');args.append(target['library_id'])
                if target['view']=='inbox':clauses.append('category_id IS NULL')
                elif target['view']=='favorites':clauses.append('favorite=1')
                elif target['view']=='repositories':clauses.append("kind='repository'")
                count=db.execute('SELECT COUNT(*) FROM resources WHERE '+' AND '.join(clauses),args).fetchone()[0]
                result.append({**row,**target,'count':count})
            return result

    def save_shortcut(self,data,sid=None):
        with self.lock,self.connect() as db:
            current=db.execute('SELECT * FROM shortcuts WHERE id=? AND deleted=0',(sid,)).fetchone() if sid else None
            if sid and not current:raise ValueError('快捷入口不存在')
            name=valid_name(data.get('name',current['name'] if current else None))
            kind=data.get('target_kind',current['target_kind'] if current else None)
            target=str(data.get('target_key',current['target_key'] if current else ''))
            self.shortcut_target(db,kind,target)
            if kind!='system':target=str(int(target))
            if db.execute('SELECT 1 FROM shortcuts WHERE target_kind=? AND target_key=? AND deleted=0 AND id!=?',(kind,target,sid or -1)).fetchone():raise ValueError('该资源库或文件夹已在快捷入口中')
            if sid:db.execute('UPDATE shortcuts SET name=?,target_kind=?,target_key=? WHERE id=?',(name,kind,target,sid))
            else:sid=db.execute('INSERT INTO shortcuts(name,target_kind,target_key,position) VALUES(?,?,?,(SELECT COALESCE(MAX(position),0)+1 FROM shortcuts))',(name,kind,target)).lastrowid
            return dict(db.execute('SELECT * FROM shortcuts WHERE id=?',(sid,)).fetchone())

    def remove_shortcut(self,sid,confirmed=False):
        if confirmed is not True:raise ValueError('请确认移除快捷入口，不会删除原资源库或链接')
        with self.lock,self.connect() as db:
            if not db.execute('SELECT 1 FROM shortcuts WHERE id=? AND deleted=0',(sid,)).fetchone():raise ValueError('快捷入口不存在')
            db.execute('UPDATE shortcuts SET deleted=1 WHERE id=?',(sid,))
        return {'removed':True}
