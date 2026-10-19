"""Exercise native-script dispatch in a JS VM, with all native functions replaced."""
from pathlib import Path
import shutil
import subprocess
import unittest


class RequestEnrichmentTests(unittest.TestCase):
    def test_background_list_skips_relationship_getters_manual_list_keeps_them(self):
        node=shutil.which('node')
        if not node:self.skipTest('Node.js unavailable')
        source=Path(__file__).resolve().parents[1]/'src/weskill/assets/friend_request_agent.js'
        script=r'''
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const context=vm.createContext({rpc:{exports:{}}});
vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),context);
vm.runInContext(`
let relations=0;
requestRecords=()=>Array.from({length:5},(_,i)=>({user_id:'fixture'+i,is_sender:false,ticket:'secret',encrypted_username:'secret'}));
requestRelation=()=>{relations++;return {is_contact:true,native_contact_flag:1}};
const background=requestDispatch({operation:'list_friend_requests',limit:0,include_contact_status:false});
if(relations!==0||background.requests.some(r=>r.status!=='unknown'||'ticket' in r))throw Error('background enrichment was not skipped');
const manual=requestDispatch({operation:'list_friend_requests',limit:0});
if(relations!==5||manual.requests.some(r=>r.status!=='already_contact'))throw Error('manual enrichment changed');
`,context);
'''
        subprocess.run([node,'-e',script,str(source)],check=True,capture_output=True,text=True)
