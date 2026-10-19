"""Durable, scheduled native pull feed. Repeated cursor reads reuse snapshots."""
import contextlib
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import threading
import time

CONTACT_INTERVAL = 15
FRIEND_INTERVAL = 60


class EventFeed:
    def __init__(self,backend,directory,*,clock=time.time):
        self.backend=backend
        self.directory=Path(directory)
        self.clock=clock
        self.lock=threading.Lock()

    def connect(self,account_id):
        self.directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        name=hashlib.sha256(account_id.encode()).hexdigest()+'.sqlite3'
        path=self.directory/name
        conn=sqlite3.connect(path,timeout=180)
        conn.row_factory=sqlite3.Row
        conn.executescript('''PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS chats(id TEXT PRIMARY KEY,recent INTEGER NOT NULL,checked REAL NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS observed(chat TEXT NOT NULL,identity TEXT NOT NULL,PRIMARY KEY(chat,identity));
        CREATE TABLE IF NOT EXISTS requests(id TEXT PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS events(cursor INTEGER PRIMARY KEY AUTOINCREMENT,kind TEXT NOT NULL,chat_id TEXT NOT NULL,payload TEXT NOT NULL,created REAL NOT NULL);
        ''')
        conn.execute('BEGIN IMMEDIATE')
        try:
            if 'checked' not in {r[1] for r in conn.execute('PRAGMA table_info(chats)')}:
                conn.execute('ALTER TABLE chats ADD COLUMN checked REAL NOT NULL DEFAULT 0')
                # An old cursor DB already baselined these unchanged sessions.
                # Upgrading must not trigger a history scan for every contact.
                conn.execute('UPDATE chats SET checked=?',(self.clock(),))
            conn.commit()
        except BaseException:
            conn.rollback()
            conn.close()
            raise
        os.chmod(path,0o600)
        return conn

    @staticmethod
    def result(response):
        if response.get('status')!='client_success' or not isinstance(response.get('result'),dict):
            raise RuntimeError('Native event read did not complete successfully: '+str(response.get('errors',[])))
        result=response['result']
        if result.get('success') is False:
            raise RuntimeError('Native event query returned success=false')
        return result

    @staticmethod
    def value(conn,key,default=None):
        row=conn.execute('SELECT value FROM metadata WHERE key=?',(key,)).fetchone()
        return row[0] if row else default

    @staticmethod
    def store(conn,key,value):
        conn.execute('INSERT INTO metadata VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,str(value)))

    def contacts(self,conn,account_id,baseline,started):
        count=int(self.value(conn,'contact_capacity',100))
        while True:
            contacts=self.result(self.backend.search_contacts([],count,False,True)).get('chat_list',[])
            if len(contacts)<count:break
            count*=2
        self.store(conn,'contact_capacity',count)
        now=self.clock()
        for chat in contacts:
            id=chat['chat_id']
            if id in {'weixin','filehelper'} or id.startswith('gh_') or id.endswith('@chatroom'):continue
            recent=int(chat.get('recent_chat_time') or 0)
            previous=conn.execute('SELECT recent,checked FROM chats WHERE id=?',(id,)).fetchone()
            if baseline and not (previous and previous['recent']==recent and recent<previous['checked']-5):
                # Expand only if the newly observed range does not fit the first
                # page. Never request unlimited historical data on every poll.
                cutoff=max(started,(previous['recent']-5) if previous else started)
                size=20
                while True:
                    result=self.result(self.backend.get_messages([id],size,False))
                    sessions=result.get('sessions')
                    if not isinstance(sessions,list):raise RuntimeError('Native history has no sessions array')
                    messages=[m for session in sessions for m in session.get('messages',[])]
                    if len(messages)<size or not messages or min(float(m.get('create_time') or 0) for m in messages)<cutoff:break
                    size*=2
                duplicates={}
                for message in messages:
                    content=json.dumps({k:message.get(k) for k in ('sender_id','create_time','message_type','message_subtype','content')},ensure_ascii=False,sort_keys=True)
                    signature=hashlib.sha256(content.encode()).hexdigest()
                    duplicates[signature]=duplicates.get(signature,0)+1
                    fallback='content:'+signature+':'+str(duplicates[signature])
                    server=str(message.get('svr_id') or '')
                    identities=[fallback]+(['server:'+server] if server not in {'','0'} else [])
                    seen=any(conn.execute('SELECT 1 FROM observed WHERE chat=? AND identity=?',(id,key)).fetchone() for key in identities)
                    for key in identities:conn.execute('INSERT OR IGNORE INTO observed VALUES(?,?)',(id,key))
                    if seen or float(message.get('create_time') or 0)<started:continue
                    payload={'account_id':account_id,'contact':chat,'message':message,'source_id':server if server not in {'','0'} else fallback}
                    conn.execute('INSERT INTO events(kind,chat_id,payload,created) VALUES(?,?,?,?)',('message',id,json.dumps(payload,ensure_ascii=False),self.clock()))
            conn.execute('INSERT INTO chats VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET recent=excluded.recent,checked=excluded.checked',(id,recent,now))
        self.store(conn,'last_contacts',self.clock())

    def friend_requests(self,conn,account_id,baseline):
        result=self.result(self.backend.list_friend_requests(0,0,False))
        rows=result.get('requests',result.get('records'))
        if not isinstance(rows,list):raise RuntimeError('Native friend request query has no requests/records array')
        for request in rows:
            id=request['request_id']
            fresh=conn.execute('INSERT OR IGNORE INTO requests VALUES(?)',(id,)).rowcount==1
            if fresh and baseline and request.get('direction')=='incoming' and request.get('native_type')==37 and request.get('status')!='already_contact':
                payload={'account_id':account_id,'request':request,'source_id':id}
                conn.execute('INSERT INTO events(kind,chat_id,payload,created) VALUES(?,?,?,?)',('friend_request',request['user_id'],json.dumps(payload,ensure_ascii=False),self.clock()))
        self.store(conn,'last_requests',self.clock())

    def read(self,account_id,cursor=0,limit=100,*,resume=False):
        if not isinstance(account_id,str) or not account_id or '\0' in account_id:raise ValueError('account_id must identify the currently logged-in WeChat account')
        if type(cursor) is not int or cursor<0 or (limit is not None and (type(limit) is not int or limit<0)) or type(resume) is not bool:raise ValueError('cursor and limit must be non-negative integers; resume must be boolean')
        with self.lock,contextlib.closing(self.connect(account_id)) as conn:
            conn.execute('BEGIN IMMEDIATE')
            try:
                if resume:conn.execute("DELETE FROM metadata WHERE key='paused_error'")
                paused=self.value(conn,'paused_error')
                baseline=self.value(conn,'started')
                if not paused:
                    started=float(baseline) if baseline is not None else self.clock()
                    if baseline is None:self.store(conn,'started',started)
                    if resume or self.clock()-float(self.value(conn,'last_contacts','-1e30'))>=CONTACT_INTERVAL:
                        self.contacts(conn,account_id,baseline is not None,started)
                    if resume or self.clock()-float(self.value(conn,'last_requests','-1e30'))>=FRIEND_INTERVAL:
                        self.friend_requests(conn,account_id,baseline is not None)
                sql='SELECT * FROM events WHERE cursor>? ORDER BY cursor';args=[cursor]
                if limit:sql+=' LIMIT ?';args.append(limit)
                events=[dict(row) for row in conn.execute(sql,args)]
                for event in events:event['payload']=json.loads(event['payload'])
                next_poll=None if paused else max(0,min(float(self.value(conn,'last_contacts'))+CONTACT_INTERVAL,float(self.value(conn,'last_requests'))+FRIEND_INTERVAL)-self.clock())
                head=conn.execute('SELECT coalesce(max(cursor),0) FROM events').fetchone()[0]
                conn.commit()
                return {'source':'native_history_poll','status':'paused' if paused else 'running','pause_reason':paused,'next_poll_seconds':next_poll,'account_id_declared':account_id,'baseline_created':baseline is None and not paused,'cursor':events[-1]['cursor'] if events else cursor,'head':head,'events':events,
                        'limitations':['Scheduled native history polling, not a push hook. Deleted/recalled messages absent from local history may be missed.','Account namespace is caller-confirmed; no automatic account switching.']}
            except Exception as error:
                conn.rollback()
                with conn:self.store(conn,'paused_error',str(error))
                raise
            except BaseException:
                conn.rollback()
                raise
