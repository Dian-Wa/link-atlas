"""Recycle recoverable JSON before removing a confirmed database record."""
import ctypes
import json
import os
import math
import uuid
from datetime import datetime


def recycle_file(path):
    if os.name!='nt':raise ValueError('此版本仅支持 Windows 回收站；数据未删除')
    class GUID(ctypes.Structure):
        _fields_=[('data',ctypes.c_ubyte*16)]
        def __init__(self,value):super().__init__();ctypes.memmove(ctypes.byref(self),uuid.UUID(value).bytes_le,16)
    ole=ctypes.OleDLL('ole32');shell=ctypes.OleDLL('shell32')
    operation=ctypes.c_void_p();item=ctypes.c_void_p()
    initialized=False
    def check(hr):
        if hr<0:raise OSError(f'Windows 回收站操作失败 (0x{hr&0xffffffff:08x})')
    def call(pointer,index,argtypes,*args):
        table=ctypes.cast(pointer,ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        return ctypes.WINFUNCTYPE(ctypes.c_long,ctypes.c_void_p,*argtypes)(table[index])(pointer,*args)
    try:
        check(ole.CoInitializeEx(None,2));initialized=True
        clsid=GUID('3AD05575-8857-4850-9277-11B85BDB8E09');iid=GUID('947AAB5F-0A5C-4C13-B4D6-4BF7836FC9F8')
        check(ole.CoCreateInstance(ctypes.byref(clsid),None,1,ctypes.byref(iid),ctypes.byref(operation)))
        shell_iid=GUID('43826D1E-E718-42EE-BC55-A1E261C37BFE')
        shell.SHCreateItemFromParsingName.argtypes=[ctypes.c_wchar_p,ctypes.c_void_p,ctypes.POINTER(GUID),ctypes.POINTER(ctypes.c_void_p)]
        check(shell.SHCreateItemFromParsingName(str(path.resolve()),None,ctypes.byref(shell_iid),ctypes.byref(item)))
        # FOFX_RECYCLEONDELETE + EARLYFAILURE; no permanent-deletion fallback.
        flags=0x00080000|0x00100000|0x0040|0x0010|0x0004|0x0400
        check(call(operation,5,[ctypes.c_uint],flags))
        check(call(operation,18,[ctypes.c_void_p,ctypes.c_void_p],item,None))
        check(call(operation,21,[]))
        aborted=ctypes.c_int()
        check(call(operation,22,[ctypes.POINTER(ctypes.c_int)],ctypes.byref(aborted)))
        if aborted.value or path.exists():raise OSError('回收站操作未完成')
    except (OSError,ValueError) as e:
        raise ValueError('无法送入 Windows 回收站，数据库记录未删除；请查看 data/recycle-staging 中的备份。'+str(e)) from e
    finally:
        if item.value:call(item,2,[])
        if operation.value:call(operation,2,[])
        if initialized:ole.CoUninitialize()


class DeletionStore:
    def _recycle_backup(self,data,kind):
        folder=self.path.parent/'recycle-staging'
        folder.mkdir(parents=True,exist_ok=True)
        path=folder/f'deleted-{kind}-{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex}.json'
        with path.open('x',encoding='utf-8') as stream:json.dump(data,stream,ensure_ascii=False,indent=2)
        recycle_file(path)
        return path.name

    def delete_resource(self,rid,confirmed=False):
        if confirmed is not True:raise ValueError('请确认删除链接并将备份送入回收站')
        from .store import decode,now
        with self.lock,self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM resources WHERE id=?',(rid,)).fetchone()
            if not row:raise ValueError('链接不存在或已删除')
            if db.execute("SELECT 1 FROM tasks WHERE resource_id=? AND status='running'",(rid,)).fetchone():raise ValueError('该链接正在抓取，请等待任务结束后再删除')
            tasks=[dict(r) for r in db.execute('SELECT * FROM tasks WHERE resource_id=?',(rid,))]
            backup={'version':1,'backup_kind':'link','exported_at':now(),'libraries':self.libraries(),'categories':self.categories(),'rules':self.rules(),
                    'resources':[decode(row)],'tasks':tasks}
            filename=self._recycle_backup(backup,'link')
            db.execute('DELETE FROM tasks WHERE resource_id=?',(rid,))
            db.execute('DELETE FROM resources WHERE id=?',(rid,))
            if db.execute('SELECT 1 FROM resources WHERE id=?',(rid,)).fetchone():raise ValueError('删除核验失败')
        return {'deleted':True,'recycled_backup':filename,'removed_tasks':len(tasks)}

    def delete_task(self,tid,confirmed=False):
        if confirmed is not True:raise ValueError('请确认删除任务记录并将备份送入回收站')
        from .store import now
        with self.lock,self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            task=db.execute('SELECT * FROM tasks WHERE id=?',(tid,)).fetchone()
            if not task:raise ValueError('任务记录不存在或已删除')
            if task['status'] in ('queued','running'):raise ValueError('排队或抓取中的任务不能删除，请等待任务结束')
            resource=db.execute('SELECT url FROM resources WHERE id=?',(task['resource_id'],)).fetchone()
            filename=self._recycle_backup({'version':1,'backup_kind':'task','exported_at':now(),'resource_url':resource['url'],'task':dict(task)},'task')
            db.execute('DELETE FROM tasks WHERE id=?',(tid,))
            if db.execute('SELECT 1 FROM tasks WHERE id=?',(tid,)).fetchone():raise ValueError('删除核验失败')
        return {'deleted':True,'recycled_backup':filename}

    def restore_task_backup(self,data):
        from .store import canonical_url
        task=data.get('task',{})
        if data.get('version')!=1 or task.get('status') not in ('success','partial','failed') or not isinstance(task.get('message',''),str):raise ValueError('无效的任务备份')
        attempts=task.get('attempts',0);next_run=task.get('next_run',0)
        if type(attempts) is not int or attempts<0 or type(next_run) not in (int,float) or not math.isfinite(next_run) or next_run<0 or not isinstance(task.get('updated_at',''),str):raise ValueError('无效的任务备份字段')
        url=canonical_url(data.get('resource_url',''))
        with self.lock,self.connect() as db:
            resource=db.execute('SELECT id FROM resources WHERE url=?',(url,)).fetchone()
            if not resource:raise ValueError('请先恢复或收录对应链接，再导入任务备份')
            values=(resource['id'],task['status'],task.get('message',''),task.get('updated_at',''))
            existing=db.execute('SELECT 1 FROM tasks WHERE resource_id=? AND status=? AND message=? AND updated_at=?',values).fetchone()
            if not existing:db.execute('INSERT INTO tasks(resource_id,status,message,updated_at,attempts,next_run) VALUES(?,?,?,?,?,?)',(*values,attempts,next_run))
        return {'created':0 if existing else 1,'duplicates':1 if existing else 0,'errors':[]}
