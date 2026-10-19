import tempfile
import sqlite3
import unittest
from pathlib import Path

from weskill.events import EventFeed
from test_events import Backend


class SchedulingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.now=1000.0;self.backend=Backend()
        self.feed=EventFeed(self.backend,self.tmp.name,clock=lambda:self.now)

    def test_capacity_and_separate_schedules_survive_new_mcp_instances(self):
        limits=[]
        def search(keywords,count,*args):
            limits.append(count)
            contacts=[{'chat_id':'gh_'+str(i)} for i in range(170)][:count]
            return {'status':'client_success','result':{'chat_list':contacts}}
        self.backend.search_contacts=search
        self.feed.read('account')
        for t in (1005,1015,1030,1045,1060):
            self.now=t
            EventFeed(self.backend,self.tmp.name,clock=lambda:self.now).read('account')
        self.assertEqual(limits,[100,200,200,200,200,200])
        self.assertEqual(self.backend.request_calls,2)
        self.assertEqual(self.backend.message_calls,[])

    def test_native_failure_pauses_across_restarts_without_repeated_queries(self):
        self.feed.read('account');self.now+=15
        self.backend.recent=1015;self.backend.fail=True
        with self.assertRaises(RuntimeError):self.feed.read('account')
        count=self.backend.search_calls
        self.now+=3600
        restarted=EventFeed(self.backend,self.tmp.name,clock=lambda:self.now)
        self.assertEqual(restarted.read('account')['status'],'paused')
        self.assertEqual(self.backend.search_calls,count)
        self.backend.fail=False
        self.assertEqual(restarted.read('account',resume=True)['status'],'running')
        self.assertEqual(self.backend.search_calls,count+1)

    def test_old_cursor_schema_upgrade_does_not_scan_unchanged_history(self):
        import hashlib
        path=Path(self.tmp.name)/(hashlib.sha256(b'account').hexdigest()+'.sqlite3')
        with sqlite3.connect(path) as conn:
            conn.executescript("CREATE TABLE chats(id TEXT PRIMARY KEY,recent INTEGER NOT NULL); INSERT INTO chats VALUES('friend',1); CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL); INSERT INTO metadata VALUES('started','900');")
        self.feed.read('account')
        self.assertEqual(self.backend.message_calls,[])

    def test_new_message_burst_expands_but_initial_baseline_does_not_read_history(self):
        self.feed.read('account')
        self.assertEqual(self.backend.message_calls,[])
        self.now+=15;self.backend.recent=1014
        messages=[{'svr_id':str(i+100),'create_time':1014,'sender_id':'friend','content':str(i)} for i in range(55)]
        sizes=[]
        def history(ids,size,xml):
            sizes.append(size)
            return {'status':'client_success','result':{'sessions':[{'chat_id':'friend','messages':messages[-size:]}]}}
        self.backend.get_messages=history
        result=self.feed.read('account')
        self.assertEqual(len(result['events']),55)
        self.assertEqual(sizes,[20,40,80])
        self.now+=15
        self.assertEqual(self.feed.read('account',result['cursor'])['events'],[])

    def test_same_second_followup_is_read_once_more_then_settles(self):
        self.feed.read('account');self.now=1015;self.backend.recent=1015
        self.backend.messages=[{'svr_id':'11','create_time':1015,'sender_id':'friend','content':'one'}]
        one=self.feed.read('account')
        self.backend.messages.append({'svr_id':'12','create_time':1015,'sender_id':'friend','content':'two'})
        self.now=1030;two=self.feed.read('account',one['cursor'])
        self.assertEqual(len(two['events']),1)
        reads=len(self.backend.message_calls)
        self.now=1045;self.feed.read('account',two['cursor'])
        self.assertEqual(len(self.backend.message_calls),reads)
