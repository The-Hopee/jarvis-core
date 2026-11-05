"""Durable bounded queue. Interrupted work is never replayed on restart."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import threading
import time
import uuid

from .config import USER_DIR
from .http import ServiceError

TERMINAL={'completed','failed','cancelled','interrupted','blocked'}


class JobCancelled(RuntimeError):pass


class JobStore:
    def __init__(self,path=None):
        self.path=Path(path or USER_DIR/'jobs.sqlite')
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('CREATE TABLE IF NOT EXISTS jobs (number INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT UNIQUE NOT NULL,kind TEXT NOT NULL,payload TEXT NOT NULL,status TEXT NOT NULL,stage TEXT NOT NULL,priority INTEGER NOT NULL,created REAL NOT NULL,updated REAL NOT NULL,cancel INTEGER NOT NULL DEFAULT 0,notified INTEGER NOT NULL DEFAULT 0,result TEXT,error TEXT,dependencies TEXT NOT NULL)')

    @contextmanager
    def connect(self):
        db=sqlite3.connect(self.path,timeout=10)
        db.row_factory=sqlite3.Row
        try:
            with db:yield db
        finally:db.close()

    @staticmethod
    def unpack(row,private=False):
        if row is None:raise ServiceError('Задача не найдена')
        value=dict(row)
        value['result']=json.loads(value['result']) if value['result'] else None
        value['dependencies']=json.loads(value['dependencies'])
        if private:value['payload']=json.loads(value['payload'])
        else:value.pop('payload',None)
        return value

    def submit(self,kind,payload,*,priority=0,dependencies=()):
        if kind not in {'chat','coding'} or not 0<=priority<=10 or len(dependencies)>8:
            raise ServiceError('Некорректная задача')
        raw=json.dumps(payload,ensure_ascii=False)
        if len(raw)>100000:raise ServiceError('Контекст задачи слишком большой')
        ident=uuid.uuid4().hex[:24];now=time.time()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute("SELECT count(*) FROM jobs WHERE status IN ('queued','running','cancel_requested')").fetchone()[0]>=16:
                raise ServiceError('Очередь заполнена. Дождитесь завершения или отмените задачу.')
            for dep in dependencies:
                if not db.execute('SELECT 1 FROM jobs WHERE id=?',(dep,)).fetchone():raise ServiceError('Зависимая задача не найдена')
            db.execute('INSERT INTO jobs(id,kind,payload,status,stage,priority,created,updated,dependencies) VALUES (?,?,?,?,?,?,?,?,?)',
                       (ident,kind,raw,'queued','queued',priority,now,now,json.dumps(list(dependencies))))
        return self.get(ident)

    def get(self,ident,*,private=False):
        with self.connect() as db:
            row=db.execute('SELECT * FROM jobs WHERE id=? OR number=?',(str(ident),int(ident) if str(ident).isdigit() and len(str(ident))<=9 else -1)).fetchone()
        return self.unpack(row,private)

    def recent(self,limit=8):
        with self.connect() as db:rows=db.execute('SELECT * FROM jobs ORDER BY number DESC LIMIT ?',(min(50,max(1,limit)),)).fetchall()
        return [self.unpack(r) for r in rows]

    def recover(self):
        with self.connect() as db:
            db.execute("UPDATE jobs SET status='interrupted',stage='needs_review',error='restart_no_replay',updated=?,notified=0 WHERE status IN ('queued','running','cancel_requested')",(time.time(),))

    def claim(self,excluded=()):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            rows=db.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY priority DESC,number").fetchall()
            for row in rows:
                if row['kind'] in excluded:continue
                deps=[db.execute('SELECT status FROM jobs WHERE id=?',(dep,)).fetchone()[0] for dep in json.loads(row['dependencies'])]
                if any(s in TERMINAL and s!='completed' for s in deps):
                    db.execute("UPDATE jobs SET status='blocked',stage='dependency_failed',updated=? WHERE id=?",(time.time(),row['id']));continue
                if any(s!='completed' for s in deps):continue
                db.execute("UPDATE jobs SET status='running',stage='starting',updated=? WHERE id=?",(time.time(),row['id']))
                return self.unpack(db.execute('SELECT * FROM jobs WHERE id=?',(row['id'],)).fetchone(),True)
        return None

    def stage(self,ident,stage):
        with self.connect() as db:db.execute('UPDATE jobs SET stage=?,updated=? WHERE id=? AND status IN (?,?)',(stage[:80],time.time(),ident,'running','cancel_requested'))

    def cancelled(self,ident):
        with self.connect() as db:row=db.execute('SELECT cancel FROM jobs WHERE id=?',(ident,)).fetchone()
        return row is None or bool(row[0])

    def cancel(self,ident):
        row=self.get(ident)
        if row['status'] in TERMINAL:return row
        with self.connect() as db:
            db.execute("UPDATE jobs SET cancel=1,status=CASE WHEN status='queued' THEN 'cancelled' ELSE 'cancel_requested' END,notified=CASE WHEN status='queued' THEN 1 ELSE 0 END,updated=? WHERE id=? AND status IN ('queued','running','cancel_requested')",(time.time(),row['id']))
        return self.get(row['id'])

    def finish(self,ident,status,*,result=None,error=None):
        if status not in TERMINAL:raise ValueError('Invalid terminal state')
        raw=json.dumps(result,ensure_ascii=False) if result is not None else None
        if raw and len(raw)>100000:raw=json.dumps({'text':'Результат слишком большой; см. файлы задачи.'})
        with self.connect() as db:
            db.execute('UPDATE jobs SET status=?,stage=?,result=?,error=?,updated=? WHERE id=?',(status,status,raw,error,time.time(),ident))
            # Retain only the most recent 500 terminal job payloads, never the
            # separate delivery receipt ledger or any unfinished work.
            db.execute("DELETE FROM jobs WHERE number NOT IN (SELECT number FROM jobs ORDER BY number DESC LIMIT 500) AND status IN ('completed','failed','cancelled','interrupted','blocked')")

    def notifications(self,*,consume=False):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            rows=db.execute("SELECT * FROM jobs WHERE notified=0 AND status IN ('completed','failed','cancelled','interrupted','blocked') ORDER BY number").fetchall()
            if consume:
                for row in rows:db.execute('UPDATE jobs SET notified=1 WHERE id=?',(row['id'],))
        return [self.unpack(row) for row in rows]

    def has_notifications(self):
        with self.connect() as db:
            return db.execute("SELECT 1 FROM jobs WHERE notified=0 AND status IN ('completed','failed','cancelled','interrupted','blocked') LIMIT 1").fetchone() is not None


class ResourceLocks:
    def __init__(self):self.guard=threading.Lock();self.locks={}

    @contextmanager
    def hold(self,key,cancelled=lambda:False):
        with self.guard:lock=self.locks.setdefault(key,threading.Lock())
        while not lock.acquire(timeout=.1):
            if cancelled():raise JobCancelled('Задача отменена до доступа к ресурсу')
        try:
            if cancelled():raise JobCancelled('Задача отменена')
            yield
        finally:lock.release()


RESOURCES=ResourceLocks()


class GuardedKernel:
    def __init__(self,kernel,cancelled):self.kernel,self.cancelled=kernel,cancelled
    def call(self,*args,**kwargs):
        if self.cancelled():raise JobCancelled('Задача отменена')
        return self.kernel.call(*args,**kwargs)


class JobDispatcher:
    def __init__(self,handlers,*,store=None,workers=2,recover=True,stopped=None):
        if not 1<=workers<=4:raise ValueError('workers: 1..4')
        self.store=store or JobStore();self.handlers=handlers;self.workers=workers
        self.stop_event=threading.Event();self.futures=set();self.pool=ThreadPoolExecutor(max_workers=workers,thread_name_prefix='jarvis-job')
        self.recover_on_start=recover
        self.coding_future=None
        self.external_stop=stopped or (lambda:False)

    def __enter__(self):
        if self.recover_on_start:self.store.recover()
        self.thread=threading.Thread(target=self._dispatch,name='jarvis-dispatch',daemon=True);self.thread.start()
        return self

    def _dispatch(self):
        while not self.stop_event.is_set() and not self.external_stop():
            self.futures={f for f in self.futures if not f.done()}
            if len(self.futures)<self.workers:
                job=self.store.claim({'coding'} if self.coding_future is not None and not self.coding_future.done() else ())
                if job:
                    if self.stop_event.is_set():self.store.finish(job['id'],'cancelled');break
                    future=self.pool.submit(self._run,job)
                    self.futures.add(future)
                    if job['kind']=='coding':self.coding_future=future
                    continue
            self.stop_event.wait(.1)

    def _run(self,job):
        cancelled=lambda:self.stop_event.is_set() or self.external_stop() or self.store.cancelled(job['id'])
        try:
            if cancelled():raise JobCancelled('Задача отменена')
            result=self.handlers[job['kind']](job,cancelled)
            self.store.finish(job['id'],'cancelled' if cancelled() else 'failed' if isinstance(result,dict) and result.get('success') is False else 'completed',result=result)
        except JobCancelled:
            self.store.finish(job['id'],'cancelled')
        except Exception as exc:
            self.store.finish(job['id'],'failed',error=type(exc).__name__)

    def __exit__(self,*_):
        self.stop_event.set();self.thread.join(timeout=2)
        deadline=time.monotonic()+55
        while any(not f.done() for f in self.futures) and time.monotonic()<deadline:time.sleep(.1)
        self.pool.shutdown(wait=False,cancel_futures=True)
