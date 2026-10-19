import tempfile
import unittest
from pathlib import Path
from weskill.events import EventFeed


class Backend:
    def __init__(self):
        self.messages=[{'svr_id':'10','sender_id':'friend','content':'old','create_time':1,'message_type':1}]
        self.requests=[]
        self.fail=False
        self.recent=1
        self.search_calls=0;self.request_calls=0;self.message_calls=[]

    def search_contacts(self,*args):
        self.search_calls+=1
        return {'status':'client_success','result':{'success':True,'chat_list':[{'chat_id':'friend','nickname':'Fixture','recent_chat_time':self.recent}]}}

    def get_messages(self,*args):
        self.message_calls.append(args)
        if self.fail:return {'status':'unknown','result':None}
        return {'status':'client_success','result':{'success':True,'sessions':[{'chat_id':'friend','messages':self.messages}]}}

    def list_friend_requests(self,*args):
        self.request_calls+=1
        return {'status':'client_success','result':{'success':True,'requests':self.requests}}


class EventTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.backend=Backend()
        self.now=1000.0
        self.feed=EventFeed(self.backend,Path(self.temp.name),clock=lambda:self.now)

    def read(self,*args,**kwargs):
        self.now+=60
        return self.feed.read(*args,**kwargs)

    def tearDown(self):self.temp.cleanup()

    def test_first_call_baselines_existing_history(self):
        result=self.read('account')
        self.assertTrue(result['baseline_created'])
        self.assertEqual(result['events'],[])

    def test_restart_cursor_and_repeated_poll_do_not_duplicate(self):
        self.read('account')
        self.backend.messages.append({'svr_id':'18446744073709551614','sender_id':'friend','content':'new','create_time':1121,'message_type':1})
        self.backend.recent=1121
        one=self.read('account')
        self.assertEqual(len(one['events']),1)
        self.assertEqual(one['events'][0]['payload']['source_id'],'18446744073709551614')
        restarted=EventFeed(self.backend,Path(self.temp.name),clock=lambda:self.now)
        self.assertEqual(restarted.read('account',one['cursor'])['events'],[])
        self.assertEqual(len(restarted.read('account',0)['events']),1)

    def test_failed_native_read_does_not_advance_observed_state(self):
        self.read('account')
        self.backend.recent=1121;self.backend.fail=True
        with self.assertRaises(RuntimeError):self.read('account')
        self.backend.fail=False
        self.backend.messages.append({'svr_id':'11','sender_id':'friend','content':'new','create_time':1121})
        self.assertEqual(len(self.read('account',resume=True)['events']),1)

    def test_server_id_assignment_does_not_reemit_local_record(self):
        self.read('account')
        local={'svr_id':'0','sender_id':'friend','content':'new','create_time':1121}
        self.backend.messages.append(local);self.backend.recent=1121
        result=self.read('account');self.assertEqual(len(result['events']),1)
        local['svr_id']='999';self.backend.recent=1122
        self.assertEqual(self.read('account',result['cursor'])['events'],[])

    def test_only_new_incoming_requests_are_emitted(self):
        self.backend.requests=[{'request_id':'old','user_id':'friend','direction':'incoming','native_type':37,'status':'unknown'}]
        self.read('account')
        self.backend.requests.append({'request_id':'new','user_id':'friend','direction':'incoming','native_type':37,'status':'unknown'})
        self.backend.requests.append({'request_id':'out','user_id':'other','direction':'outgoing','native_type':37,'status':'unknown'})
        self.backend.requests.append({'request_id':'known','user_id':'known','direction':'incoming','native_type':37,'status':'already_contact'})
        self.backend.requests.append({'request_id':'unsupported','user_id':'unsupported','direction':'incoming','native_type':99,'status':'unknown'})
        result=self.read('account')
        self.assertEqual([e['payload']['source_id'] for e in result['events']],['new'])


class FrequencyRegressionTests(unittest.TestCase):
    def test_twenty_rapid_mcp_polls_reuse_native_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            backend=Backend();feed=EventFeed(backend,directory)
            for _ in range(20):feed.read('account')
            self.assertEqual(backend.search_calls,1)
            self.assertEqual(backend.request_calls,1)
            self.assertEqual(backend.message_calls,[])


if __name__=='__main__':unittest.main()
