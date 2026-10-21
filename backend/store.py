import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from .navigation import NavigationStore, descendants, valid_name, valid_icon, SYSTEM_SHORTCUTS
from .deletion import DeletionStore


DEFAULTS = ['开发工具', 'AI', '学习资料', '设计资源', '实用网站', '其他']
BOOTSTRAP_RULES = [
                    ('github,gitlab,代码,开发,工具,developer,typescript,javascript,rust,python,java,c++,c#', 1),
                    ('机器学习,人工智能,大模型,llm,openai,huggingface,模型,ai,deep learning', 2),
                    ('教程,课程,学习,文档,docs,tutorial,course', 3),
                    ('设计,配色,字体,figma,design,icon', 4)]
JSON_FIELDS = {'tags': [], 'repo': {}, 'manual_fields': []}
EDITABLE = {'title', 'description', 'category_id', 'tags', 'notes', 'kind', 'favorite', 'archived', 'library_id'}


def now():
    return datetime.now(timezone.utc).isoformat()


def canonical_url(value):
    value = value.strip()
    if len(value) > 4096:
        raise ValueError('链接过长')
    p = urlsplit(value)
    if p.scheme.lower() not in ('http', 'https') or not p.hostname or p.username or p.password:
        raise ValueError('只支持不含账号密码的 HTTP/HTTPS 链接')
    if any(ord(c) < 33 for c in value):
        raise ValueError('链接含无效字符')
    host = p.hostname.encode('idna').decode().lower()
    if ':' in host:
        host = f'[{host}]'
    port = p.port
    if port and not (p.scheme.lower() == 'https' and port == 443 or p.scheme.lower() == 'http' and port == 80):
        host += f':{port}'
    return urlunsplit((p.scheme.lower(), host, p.path or '/', p.query, ''))


def decode(row):
    if row is None:
        return None
    r = dict(row)
    for k, default in JSON_FIELDS.items():
        if k in r:
            r[k] = json.loads(r[k]) if r[k] else default
    return r


class Store(NavigationStore,DeletionStore):
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS categories(id INTEGER PRIMARY KEY, name TEXT NOT NULL, parent_id INTEGER REFERENCES categories(id), UNIQUE(name,parent_id));
                CREATE TABLE IF NOT EXISTS resources(
                    id INTEGER PRIMARY KEY, url TEXT NOT NULL UNIQUE, title TEXT NOT NULL DEFAULT '',
                    description TEXT NOT NULL DEFAULT '', category_id INTEGER REFERENCES categories(id),
                    tags TEXT NOT NULL DEFAULT '[]', notes TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL DEFAULT 'link',
                    favorite INTEGER NOT NULL DEFAULT 0, archived INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'queued', repo TEXT NOT NULL DEFAULT '{}', manual_fields TEXT NOT NULL DEFAULT '[]',
                    classification_reason TEXT NOT NULL DEFAULT '', fetch_message TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE IF NOT EXISTS tasks(id INTEGER PRIMARY KEY, resource_id INTEGER NOT NULL REFERENCES resources(id),
                    status TEXT NOT NULL DEFAULT 'queued', attempts INTEGER NOT NULL DEFAULT 0, next_run REAL NOT NULL DEFAULT 0,
                    message TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
                CREATE INDEX IF NOT EXISTS resources_filter ON resources(archived,category_id,kind,status);
                CREATE INDEX IF NOT EXISTS tasks_ready ON tasks(status,next_run);
                CREATE TABLE IF NOT EXISTS rules(id INTEGER PRIMARY KEY, keywords TEXT NOT NULL, category_id INTEGER NOT NULL REFERENCES categories(id));
                CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value INTEGER NOT NULL);
            ''')
            if not db.execute('SELECT 1 FROM categories LIMIT 1').fetchone():
                db.executemany('INSERT INTO categories(name) VALUES(?)', [(x,) for x in DEFAULTS])
                db.executemany('INSERT INTO rules(keywords,category_id) VALUES(?,?)', BOOTSTRAP_RULES)
            self.migrate_navigation(db)
            db.execute("UPDATE tasks SET status='queued',message='应用重启，恢复排队' WHERE status='running'")
            db.execute("UPDATE resources SET status='queued' WHERE id IN (SELECT resource_id FROM tasks WHERE status='queued')")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    def settings(self):
        with self.connect() as db:
            row = db.execute("SELECT value FROM settings WHERE key='page_limit_mib'").fetchone()
            return {'page_limit_mib': row['value'] if row else 2}

    @staticmethod
    def validate_settings(data):
        if not isinstance(data, dict) or set(data) != {'page_limit_mib'}:
            raise ValueError('仅支持设置网页读取上限')
        value = data['page_limit_mib']
        if type(value) is not int or not 1 <= value <= 10:
            raise ValueError('网页读取上限必须为 1–10 MiB 的整数')
        return value

    def save_settings(self, data):
        value = self.validate_settings(data)
        with self.lock, self.connect() as db:
            db.execute("INSERT INTO settings(key,value) VALUES('page_limit_mib',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (value,))
        return self.settings()

    def categories(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT c.*,COUNT(r.id) count FROM categories c LEFT JOIN resources r ON r.category_id=c.id AND r.archived=0 WHERE c.deleted=0 GROUP BY c.id ORDER BY c.library_id,c.position,c.id')]

    def rules(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT rules.* FROM rules JOIN categories c ON c.id=rules.category_id WHERE c.deleted=0 ORDER BY rules.id DESC')]

    def save_rule(self, data, rid=None):
        keywords = str(data.get('keywords', '')).strip()
        if not keywords or len(keywords) > 1000:
            raise ValueError('请输入不超过 1000 字的逗号分隔关键词')
        with self.connect() as db:
            if not db.execute('SELECT 1 FROM categories WHERE id=? AND deleted=0', (data.get('category_id'),)).fetchone():
                raise ValueError('分类不存在')
            if rid:
                db.execute('UPDATE rules SET keywords=?,category_id=? WHERE id=?', (keywords, data['category_id'], rid))
            else:
                rid = db.execute('INSERT INTO rules(keywords,category_id) VALUES(?,?)', (keywords, data['category_id'])).lastrowid
            return {'id': rid, 'keywords': keywords, 'category_id': data['category_id']}

    def add_urls(self, urls, library_id=None, category_id=None):
        if len(urls) > 1000:
            raise ValueError('每批最多 1000 条链接')
        result = {'created': 0, 'duplicates': 0, 'errors': []}
        with self.lock, self.connect() as db:
            library_id = self.folder_library(db,library_id,category_id)
            if library_id is None:library_id=self.default_library(db)
            for raw in urls:
                try:
                    url = canonical_url(raw)
                except (ValueError, TypeError, AttributeError) as e:
                    result['errors'].append({'url': str(raw)[:200], 'message': str(e)})
                    continue
                if db.execute('SELECT id FROM resources WHERE url=?', (url,)).fetchone():
                    result['duplicates'] += 1
                    continue
                rid = db.execute('INSERT INTO resources(url,title,library_id,category_id,manual_fields) VALUES(?,?,?,?,?)', (url, urlsplit(url).hostname,library_id,category_id,json.dumps(['category_id'] if category_id else []))).lastrowid
                db.execute('INSERT INTO tasks(resource_id) VALUES(?)', (rid,))
                result['created'] += 1
        return result

    def get(self, rid):
        with self.connect() as db:
            return decode(db.execute('SELECT * FROM resources WHERE id=?', (rid,)).fetchone())

    def edit(self, rid, data):
        with self.lock, self.connect() as db:
            r = decode(db.execute('SELECT * FROM resources WHERE id=?', (rid,)).fetchone())
            if not r:
                raise ValueError('资源不存在')
            data=dict(data)
            if 'library_id' in data or 'category_id' in data:
                cid=data.get('category_id',r['category_id'])
                lid=data.get('library_id',r['library_id'])
                if cid is not None and 'library_id' in data and lid is None:raise ValueError('文件夹必须归属于资源库')
                if 'library_id' in data and lid!=r['library_id'] and 'category_id' not in data:cid=None;data['category_id']=None
                if cid and 'library_id' not in data:lid=self.folder_library(db,None,cid);data['library_id']=lid
                self.folder_library(db,lid,cid)
            fields = set(r['manual_fields'])
            updates = {}
            for k, v in data.items():
                if k not in EDITABLE:
                    continue
                if k == 'category_id' and v is not None and not db.execute('SELECT 1 FROM categories WHERE id=?', (v,)).fetchone():
                    raise ValueError('分类不存在')
                if k == 'kind' and v not in ('link', 'repository'):
                    raise ValueError('无效资源类型')
                if k == 'tags':
                    if not isinstance(v, list) or len(v) > 30 or any(not isinstance(x, str) or len(x) > 60 for x in v):
                        raise ValueError('标签最多 30 个，每个不超过 60 字')
                    v = json.dumps(list(dict.fromkeys(x.strip() for x in v if x.strip())), ensure_ascii=False)
                elif k in ('favorite', 'archived'):
                    v = int(bool(v))
                elif k not in ('category_id','library_id'):
                    if not isinstance(v, str) or len(v) > (20000 if k == 'notes' else 4000):
                        raise ValueError('字段内容过长或格式错误')
                updates[k] = v
                if k not in ('favorite', 'archived'):
                    fields.add(k)
            updates['manual_fields'] = json.dumps(sorted(fields))
            updates['updated_at'] = now()
            db.execute('UPDATE resources SET ' + ','.join(f'{k}=?' for k in updates) + ' WHERE id=?', (*updates.values(), rid))
        return self.get(rid)

    def list_resources(self, q='', page=1, view='all', category_id=None, kind='', status='', tag='',library_id=None):
        page = max(1, page)
        clauses, args = ['archived=?'], [int(view == 'archived')]
        if view == 'favorites':
            clauses.append('favorite=1')
        elif view == 'inbox':
            clauses.append('category_id IS NULL')
        elif view == 'repositories':
            clauses.append("kind='repository'")
        if category_id:
            clauses.append('category_id IN (WITH RECURSIVE tree(id) AS (SELECT id FROM categories WHERE id=? AND deleted=0 UNION ALL SELECT c.id FROM categories c JOIN tree ON c.parent_id=tree.id WHERE c.deleted=0) SELECT id FROM tree)')
            args.append(category_id)
        if library_id:
            clauses.append('library_id=?');args.append(library_id)
        for field, value in [('kind', kind), ('status', status)]:
            if value:
                clauses.append(f'{field}=?')
                args.append(value)
        if tag:
            clauses.append('EXISTS (SELECT 1 FROM json_each(resources.tags) WHERE value=?)')
            args.append(tag)
        if q:
            clauses.append("(title LIKE ? ESCAPE '\\' OR url LIKE ? ESCAPE '\\' OR description LIKE ? ESCAPE '\\' OR tags LIKE ? ESCAPE '\\' OR notes LIKE ? ESCAPE '\\')")
            pattern = '%' + q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
            args.extend([pattern] * 5)
        where = ' AND '.join(clauses)
        with self.connect() as db:
            count = db.execute('SELECT COUNT(*) FROM resources WHERE ' + where, args).fetchone()[0]
            rows = db.execute('SELECT * FROM resources WHERE ' + where + ' ORDER BY created_at DESC,id DESC LIMIT 50 OFFSET ?', (*args, (page-1)*50))
            return {'items': [decode(r) for r in rows], 'total': count, 'page': page, 'page_size': 50}

    def stats(self):
        with self.connect() as db:
            r = dict(db.execute("SELECT COUNT(*) total,COALESCE(SUM(favorite),0) favorites,COALESCE(SUM(kind='repository'),0) repositories,COALESCE(SUM(category_id IS NULL),0) inbox FROM resources WHERE archived=0").fetchone())
            r['active_tasks'] = db.execute("SELECT COUNT(*) FROM tasks WHERE status IN ('queued','running')").fetchone()[0]
            r['tags'] = [dict(x) for x in db.execute('SELECT value name,COUNT(*) count FROM resources,json_each(resources.tags) WHERE archived=0 GROUP BY value ORDER BY count DESC LIMIT 20')]
            return r

    def tasks(self, page=1):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT t.*,r.title,r.url FROM tasks t JOIN resources r ON r.id=t.resource_id ORDER BY t.id DESC LIMIT 50 OFFSET ?', ((max(1,page)-1)*50,))]

    def task_count(self):
        with self.connect() as db:
            return db.execute('SELECT COUNT(*) FROM tasks').fetchone()[0]

    def claim_task(self):
        import time
        with self.lock, self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            task = db.execute("SELECT t.*,r.url FROM tasks t JOIN resources r ON r.id=t.resource_id WHERE t.status='queued' AND t.next_run<=? ORDER BY t.id LIMIT 1", (time.time(),)).fetchone()
            if not task:
                return None
            db.execute("UPDATE tasks SET status='running',updated_at=? WHERE id=?", (now(), task['id']))
            db.execute("UPDATE resources SET status='running' WHERE id=?", (task['resource_id'],))
            return {**dict(task), 'status': 'running'}

    def finish_task(self, tid, status, message='', delay=None):
        import time
        with self.lock, self.connect() as db:
            task = db.execute('SELECT * FROM tasks WHERE id=?', (tid,)).fetchone()
            if delay is not None:
                status = 'queued'
            db.execute('UPDATE tasks SET status=?,message=?,attempts=attempts+1,next_run=?,updated_at=? WHERE id=?', (status, message[:1000], time.time()+(delay or 0), now(), tid))
            db.execute('UPDATE resources SET status=?,fetch_message=? WHERE id=?', (status, message[:1000], task['resource_id']))

    def retry(self, rid):
        with self.lock, self.connect() as db:
            if not db.execute('SELECT 1 FROM resources WHERE id=?', (rid,)).fetchone():
                raise ValueError('资源不存在')
            if db.execute("SELECT 1 FROM tasks WHERE resource_id=? AND status IN ('queued','running')", (rid,)).fetchone():
                return {'queued': False, 'message': '已有任务正在处理'}
            db.execute('INSERT INTO tasks(resource_id) VALUES(?)', (rid,))
            db.execute("UPDATE resources SET status='queued' WHERE id=?", (rid,))
        return {'queued': True}

    def apply_fetch(self, rid, data, status, message=''):
        with self.lock, self.connect() as db:
            r = decode(db.execute('SELECT * FROM resources WHERE id=?', (rid,)).fetchone())
            updates = {k: v for k, v in data.items() if k in {'title','description','category_id','tags','kind','repo','classification_reason'} and k not in r['manual_fields']}
            if updates.get('category_id') is not None:
                cat=db.execute('SELECT library_id FROM categories WHERE id=? AND deleted=0',(updates['category_id'],)).fetchone()
                if not cat or cat['library_id']!=r['library_id']:updates.pop('category_id',None)
            for k in ('tags', 'repo'):
                if k in updates:
                    updates[k] = json.dumps(updates[k], ensure_ascii=False)
            updates.update(status=status, fetch_message=message[:1000], updated_at=now())
            db.execute('UPDATE resources SET ' + ','.join(f'{k}=?' for k in updates) + ' WHERE id=?', (*updates.values(), rid))

    def export_data(self):
        with self.connect() as db:
            return {'version': 1, 'exported_at': now(), 'settings': self.settings(), 'libraries':self.libraries(), 'shortcuts':self.shortcuts(), 'categories': [dict(r) for r in db.execute('SELECT * FROM categories WHERE deleted=0 ORDER BY position,id')],
                    'rules': self.rules(), 'resources': [decode(r) for r in db.execute('SELECT * FROM resources')],
                    'tasks': [dict(r) for r in db.execute('SELECT * FROM tasks')]}

    def export_info(self):
        with self.connect() as db:
            count = db.execute('SELECT COUNT(*) FROM resources').fetchone()[0]
            # Conservative UTF-8 estimate; actual export enforces the precise byte limit.
            size = db.execute("SELECT COALESCE(SUM(length(CAST(url||title||description||tags||notes||repo||manual_fields||classification_reason||fetch_message AS BLOB))+600),0) FROM resources").fetchone()[0]
            size += db.execute('SELECT COALESCE(SUM(length(CAST(message AS BLOB))+300),0) FROM tasks').fetchone()[0]
            return {'resource_count': count, 'estimated_json_bytes': size, 'json_supported': count <= 100000 and size < 31*1024*1024}

    def snapshot(self, destination):
        with self.connect() as source, sqlite3.connect(destination) as target:
            source.backup(target)

    def import_data(self, data):
        if data.get('version') != 1 or not isinstance(data.get('resources'), list):
            raise ValueError('不支持的备份格式')
        if len(data['resources']) > 100000:
            raise ValueError('单次导入最多 100000 条')
        settings_value = self.validate_settings(data['settings']) if 'settings' in data else None
        # Validate all input before writing; a malformed backup never leaves a partial import.
        resources = []
        for r in data['resources']:
            url = canonical_url(r['url'])
            if not isinstance(r.get('tags', []), list) or any(not isinstance(x, str) for x in r.get('tags', [])):
                raise ValueError('无效标签')
            if len(r.get('tags', [])) > 30 or any(len(x) > 60 for x in r.get('tags', [])):
                raise ValueError('标签最多 30 个，每个不超过 60 字')
            if r.get('kind', 'link') not in ('link', 'repository'):
                raise ValueError('无效资源类型')
            if not isinstance(r.get('repo', {}), dict) or not isinstance(r.get('manual_fields', []), list):
                raise ValueError('无效资源数据')
            if any(not isinstance(x,str) or x not in EDITABLE for x in r.get('manual_fields', [])):
                raise ValueError('无效人工保护字段')
            if any(r.get(k, 0) not in (0,1,False,True) for k in ('favorite','archived')):
                raise ValueError('无效收藏或归档状态')
            if r.get('status', 'queued') not in ('queued','running','success','partial','failed'):
                raise ValueError('无效抓取状态')
            repo = r.get('repo', {})
            if any(repo.get(k) is not None and not isinstance(repo[k],str) for k in ('language','license','updated_at','readme')):
                raise ValueError('无效项目索引文本')
            if repo.get('stars') is not None and (type(repo['stars']) is not int or repo['stars'] < 0):
                raise ValueError('无效 Star 数量')
            if not isinstance(repo.get('topics',[]),list) or any(not isinstance(x,str) for x in repo.get('topics',[])):
                raise ValueError('无效项目主题')
            if any(not isinstance(r.get(k, ''), str) for k in ('title','description','notes')):
                raise ValueError('无效资源文本')
            if any(not isinstance(r.get(k, ''), str) for k in ('created_at','updated_at','classification_reason','fetch_message')):
                raise ValueError('无效资源元信息')
            resources.append((url, r))
        created = duplicates = 0
        with self.lock, self.connect() as db:
            if settings_value is not None:
                db.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('page_limit_mib',?)", (settings_value,))
            # Restore exact navigation in a pristine workspace; never replace user metadata.
            bootstrap_libraries=[tuple(row) for row in db.execute('SELECT id,name,position,deleted,icon FROM libraries ORDER BY id')]
            bootstrap_categories=[tuple(row) for row in db.execute('SELECT id,name,parent_id,library_id,position,deleted FROM categories ORDER BY id')]
            bootstrap_rules=[tuple(row) for row in db.execute('SELECT keywords,category_id FROM rules ORDER BY id')]
            pristine=(not db.execute('SELECT 1 FROM resources LIMIT 1').fetchone()
                      and bootstrap_libraries==[(1,'我的资源库',0,0,'library')]
                      and bootstrap_categories==[(i,name,None,1,i,0) for i,name in enumerate(DEFAULTS,1)]
                      and bootstrap_rules==list(BOOTSTRAP_RULES))
            pristine_shortcuts=[(r['target_key'],r['name'],r['position']) for r in db.execute("SELECT * FROM shortcuts WHERE deleted=0 ORDER BY position,id")]==[(key,name,i) for i,(key,name) in enumerate(SYSTEM_SHORTCUTS)]
            pristine=pristine and pristine_shortcuts
            if 'libraries' in data and pristine:
                db.execute('UPDATE libraries SET deleted=1')
                db.execute("UPDATE categories SET deleted=1,name=name||' [初始化:'||id||']'")
            library_map={}
            for lib in data.get('libraries',[]):
                name=valid_name(lib['name']);icon=valid_icon(lib.get('icon','library'))
                existing=db.execute('SELECT id FROM libraries WHERE name=? AND deleted=0',(name,)).fetchone()
                library_map[lib['id']]=existing['id'] if existing else db.execute('INSERT INTO libraries(name,position,icon) VALUES(?,?,?)',(name,lib.get('position',0),icon)).lastrowid
            mapping = {}
            pending=list(data.get('categories', []))
            while pending:
                progress=False
                for c in pending[:]:
                    if c.get('parent_id') is not None and c['parent_id'] not in mapping:continue
                    name=valid_name(c['name'])
                    parent=mapping.get(c.get('parent_id'))
                    lid=library_map.get(c.get('library_id'),self.default_library(db))
                    if parent:
                        plid=db.execute('SELECT library_id FROM categories WHERE id=?',(parent,)).fetchone()[0]
                        if lid!=plid:raise ValueError('备份文件夹跨资源库')
                    if lid is None:raise ValueError('备份缺少资源库')
                    existing=db.execute('SELECT id FROM categories WHERE name=? AND parent_id IS ? AND library_id=? AND deleted=0',(name,parent,lid)).fetchone()
                    mapping[c['id']]=existing['id'] if existing else db.execute('INSERT INTO categories(name,parent_id,library_id,position) VALUES(?,?,?,?)',(name,parent,lid,c.get('position',0))).lastrowid
                    pending.remove(c);progress=True
                if not progress:raise ValueError('备份含无效分类层级或循环')
            if 'shortcuts' in data:
                if pristine and pristine_shortcuts:db.execute('UPDATE shortcuts SET deleted=1')
                for shortcut in data['shortcuts']:
                    name=valid_name(shortcut['name']);kind=shortcut['target_kind'];target=str(shortcut['target_key'])
                    if kind=='library':
                        if int(target) not in library_map:raise ValueError('快捷入口引用的资源库不存在')
                        target=str(library_map[int(target)])
                    elif kind=='folder':
                        if int(target) not in mapping:raise ValueError('快捷入口引用的文件夹不存在')
                        target=str(mapping[int(target)])
                    self.shortcut_target(db,kind,target)
                    if not db.execute('SELECT 1 FROM shortcuts WHERE target_kind=? AND target_key=? AND deleted=0',(kind,target)).fetchone():
                        db.execute('INSERT INTO shortcuts(name,target_kind,target_key,position) VALUES(?,?,?,?)',(name,kind,target,shortcut.get('position',0)))
            for rule in data.get('rules', []):
                cat = mapping.get(rule['category_id'])
                if not cat:
                    raise ValueError('规则分类不存在')
                if not db.execute('SELECT 1 FROM rules WHERE keywords=? AND category_id=?', (rule['keywords'], cat)).fetchone():
                    db.execute('INSERT INTO rules(keywords,category_id) VALUES(?,?)', (str(rule['keywords'])[:1000], cat))
            idmap = {}
            for url, r in resources:
                if db.execute('SELECT id FROM resources WHERE url=?', (url,)).fetchone():
                    duplicates += 1
                    continue
                if r.get('category_id') is not None and r['category_id'] not in mapping:raise ValueError('备份引用的文件夹不存在')
                if 'libraries' in data and r.get('library_id') is not None and r['library_id'] not in library_map:raise ValueError('备份引用的资源库不存在')
                values = {'url': url, **{k: r[k] for k in EDITABLE if k in r}, 'category_id': mapping.get(r.get('category_id')),
                          'library_id': library_map.get(r.get('library_id')) if 'library_id' in r and r['library_id'] is None else library_map.get(r.get('library_id'),self.default_library(db)),
                          'status': r.get('status', 'queued'), 'repo': r.get('repo', {}), 'manual_fields': r.get('manual_fields', []),
                          'classification_reason': r.get('classification_reason', ''), 'fetch_message': r.get('fetch_message', ''),
                          'created_at': r.get('created_at', now()), 'updated_at': r.get('updated_at', now())}
                if values['category_id'] is not None and values['library_id'] is None:raise ValueError('备份文件夹缺少资源库')
                self.folder_library(db,values['library_id'],values['category_id'])
                if values['status'] == 'running':
                    values['status'] = 'queued'
                for k in JSON_FIELDS:
                    if k in values:
                        values[k] = json.dumps(values[k], ensure_ascii=False)
                rid = db.execute('INSERT INTO resources(' + ','.join(values) + ') VALUES(' + ','.join('?' for _ in values) + ')', tuple(values.values())).lastrowid
                idmap[r.get('id')] = rid
                created += 1
            task_resources = set()
            for t in data.get('tasks', []):
                rid = idmap.get(t['resource_id'])
                if rid:
                    status = 'queued' if t['status'] == 'running' else t['status']
                    db.execute('INSERT INTO tasks(resource_id,status,attempts,next_run,message,updated_at) VALUES(?,?,?,?,?,?)', (rid,status,t.get('attempts',0),t.get('next_run',0),t.get('message',''),t.get('updated_at',now())))
                    task_resources.add(rid)
            for rid in idmap.values():
                if rid not in task_resources and db.execute('SELECT status FROM resources WHERE id=?', (rid,)).fetchone()[0] == 'queued':
                    db.execute('INSERT INTO tasks(resource_id) VALUES(?)', (rid,))
        return {'created': created, 'duplicates': duplicates, 'errors': []}
