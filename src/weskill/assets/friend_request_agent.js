'use strict';
// Native friend-request records from the client's FMessageService.
const requestState={prepared:false,invoked:false,completed:false,destroyed:false,
 invocationCount:0,completionCount:0,errors:[]};
const requestKeep={strings:[]};
function requestNative(offset,ret,args){return new NativeFunction(requestKeep.main.base.add(offset),ret,args);}
function requestValidate(offset,words){const p=requestKeep.main.base.add(offset);words.forEach((w,i)=>{if(p.add(i*4).readU32()!==w)throw new Error('Friend-request entry mismatch at '+offset.toString(16));});return p;}
function requestReadString(p){const flag=p.readU8();const n=(flag&1)?p.add(8).readU64().toNumber():flag>>>1;if(!(flag&1)&&n>22)throw new Error('Invalid native short string');return n?((flag&1)?p.add(16).readPointer():p.add(1)).readUtf8String(n):'';}
function requestSret(offset,out,args=[]){const values=args.slice();while(values.length<4)values.push(ptr(0));requestKeep.sret(...values,out,requestKeep.main.base.add(offset));}
function requestShared(offset,args=[]){const out=Memory.alloc(16);out.writeByteArray(new Uint8Array(16));requestSret(offset,out,args);requestKeep.shared.push(out);return out.readPointer();}
function requestService(){const context=requestShared(0x5eee0b4);if(context.isNull())throw new Error('No logged-in context');const session=requestShared(0x602cd40,[context]);const service=requestShared(0x6089d34,[session]);if(service.isNull())throw new Error('No native friend-request service');return service;}
function requestRecords(){
 requestValidate(0x623a8a4,[0xd100c3ff,0xa9017bfd,0xf90013f3,0x910043fd]);
 const out=Memory.alloc(24);out.writeByteArray(new Uint8Array(24));requestSret(0x623a8a4,out,[requestService()]);
 const begin=out.readPointer(),end=out.add(8).readPointer();const bytes=end.sub(begin).toInt32();
 if(bytes<0||bytes%0x108)throw new Error('Invalid native friend-request vector');
 const rows=[];
 try {for(let offset=0;offset<bytes;offset+=0x108){const p=begin.add(offset);const username=requestReadString(p);const timestamp=p.add(0x1c).readU32();const type=p.add(0x18).readU32();
  rows.push({request_id:JSON.stringify([username,timestamp,type]),user_id:username,native_type:type,timestamp,
   encrypted_username:requestReadString(p.add(0x20)),greeting:requestReadString(p.add(0x38)),is_sender:!!p.add(0x50).readU8(),
   ticket:requestReadString(p.add(0x58)),scene:p.add(0x70).readU32(),remark:requestReadString(p.add(0x90)),label_ids:requestReadString(p.add(0xa8)),status:'unknown'});
 }} finally {for(let offset=bytes-0x108;offset>=0;offset-=0x108)requestNative(0x614c834,'void',['pointer'])(begin.add(offset));if(!begin.isNull())requestNative(0x4499070,'void',['pointer'])(begin);}
 rows.sort((a,b)=>b.timestamp-a.timestamp);return rows;
}
function requestString(text){
 const data=Memory.allocUtf8String(text),out=Memory.alloc(24),n=unescape(encodeURIComponent(text)).length;
 out.writeByteArray(new Uint8Array(24));
 if(n<=22){out.writeU8(n*2);out.add(1).writeUtf8String(text);}
 else{out.writeU64(uint64(Math.ceil((n+1)/16)*16).or(1));out.add(8).writeU64(n);out.add(16).writePointer(data);}
 requestKeep.strings.push(data,out);return out;
}
function requestSession(){const context=requestShared(0x5eee0b4);if(context.isNull())throw new Error('No logged-in context');return requestShared(0x602cd40,[context]);}
function requestRelation(id){
 const contacts=requestShared(0x5faa590,[requestSession()]);
 const contact=requestShared(0x7547d4c,[contacts,requestString(id)]);
 if(contact.isNull())return {is_contact:false,native_contact_flag:0};
 const flags=contact.add(0x54).readU32();
 // Same bit admitted by native contact::search_contacts at 0x6c93094.
 return {is_contact:(flags&1)!==0,native_contact_flag:flags};
}
function requestPublic(row,includeContactStatus=true){
 const value=Object.assign({},row,includeContactStatus?requestRelation(row.user_id):{is_contact:null,native_contact_flag:null});
 value.direction=row.is_sender?'outgoing':'incoming';
 // A current contact is established; other records may have expired or were
 // declined elsewhere, so absence from contacts does not establish pending.
 value.status=value.is_contact?'already_contact':'unknown';
 delete value.ticket;delete value.encrypted_username;return value;
}
// These nontrivial C++ results use AAPCS64 indirect aggregate return in x8.
// libffi supplies that register for an 88-byte aggregate, retaining all ten
// ordinary argument positions, including the two stack arguments for add.
function requestVerify(offset,types,args){
 const words=requestNative(offset,Array(11).fill('uint64'),types)(...args),out=Memory.alloc(0x58);
 words.forEach((word,i)=>out.add(i*8).writeU64(word));
 try{return {success:out.readU8()!==0,submission_unknown:false,native_error_code:out.add(4).readS32(),
  error_message:requestReadString(out.add(8)),native_opcode:out.add(0x20).readU32()};}
 finally{requestNative(0x4ddf680,'void',['pointer'])(out);}
}
function requestAccept(parameters){
 const row=requestRecords().find(row=>row.request_id===parameters.request_id);
 if(!row)return {success:false,not_submitted:true,error_message:'Friend request no longer exists in the native local list'};
 if(row.is_sender||row.native_type!==37)return {success:false,not_submitted:true,error_message:'Selected record is not an incoming friend request'};
 if(!row.ticket)return {success:false,not_submitted:true,error_message:'Native friend request has no verification ticket'};
 const relation=requestRelation(row.user_id);
 if(relation.is_contact)return {success:false,not_submitted:true,already_friend:true,user_id:row.user_id,error_message:'Selected requester is already a native contact'};
 const service=requestShared(0x6fecd28,[requestSession()]);
 if(service.isNull())throw new Error('No native verification service');
 requestValidate(0x66e3758,[0xd10243ff,0xa9057bfd,0xa9065ff8,0xa90757f6]);
 const result=requestVerify(0x66e3758,['pointer','pointer','uint','uint','pointer','pointer','pointer'],
  [service,requestString(row.user_id),row.scene,0,requestString(row.ticket),
   requestString(parameters.remark==null?row.remark:parameters.remark),requestString(row.label_ids)]);
 return Object.assign(result,{request_id:row.request_id,user_id:row.user_id,source:'native_verifyuser'});
}
function requestSearch(query){
 requestState.stage='construct_search_request';
 // SearchContactRequest::UserName (field 2) and SearchScene (field 6=1)
 // follow the native search-friend call at 0x7015664. Allocate owned nested
 // protobuf objects with the client's allocator so its destructor can free them.
 requestValidate(0x700f258,[0xfc190fe8,0xa9017bfd,0xa9026ffc,0xa90367fa]);
 const proto=Memory.alloc(0x38);requestNative(0x7b1e994,'void',['pointer'])(proto);
 const name=requestNative(0x9fa44e8,'pointer',['uint64'])(24);
 requestNative(0x78489ec,'void',['pointer'])(name);
 const nameValue=requestNative(0x9fa44e8,'pointer',['uint64'])(24);nameValue.writeByteArray(new Uint8Array(24));
 requestNative(0x449cf38,'void',['pointer','pointer'])(nameValue,requestString(query));
 name.add(8).writePointer(nameValue);name.add(0x14).writeU32(1);
 proto.add(0x10).writePointer(name);proto.add(0x28).writeU32(1);proto.add(0x30).writeU32(0x22);
 const config=Memory.alloc(40),out=Memory.alloc(48);config.writeByteArray(new Uint8Array(40));out.writeByteArray(new Uint8Array(48));
 config.writeByteArray(requestKeep.main.base.add(0x2333820).readByteArray(8));
 try{
  requestState.stage='execute_search';requestSret(0x700f258,out,[ptr(0),proto,requestString(''),config]);
  requestState.stage='decode_search_result';const result={success:out.readS32()===0&&out.add(4).readS32()===0,
   native_error_type:out.readS32(),native_error_code:out.add(4).readS32(),error_message:requestReadString(out.add(8))};
  if(!result.success)return result;
  const response=out.add(0x20).readPointer();if(response.isNull())throw new Error('Native search returned no response');
  const username=response.add(0x10).readPointer(),ticket=response.add(0xe8).readPointer();
  result.user_id=username.isNull()||username.add(8).readPointer().isNull()?'':requestReadString(username.add(8).readPointer());
  result.ticket=ticket.isNull()?'':requestReadString(ticket);
  if(!result.user_id)throw new Error('Native search returned no user ID');
  return result;
 }finally{requestNative(0x700f924,'void',['pointer'])(out);requestNative(0x7b1ec2c,'void',['pointer'])(proto);}
}
function requestAdd(parameters){
 // Use Linux's generic verification entry (0x531e518), whose scene is 0.
 // Search-source-specific scene selection has not been established.
 let target;try{target=requestSearch(parameters.query);}catch(error){return {success:false,not_submitted:true,error_message:String(error),stage:requestState.stage,source:'native_searchcontact'};}
 if(!target.success)return Object.assign(target,{not_submitted:true,source:'native_searchcontact'});
 const relation=requestRelation(target.user_id);
 if(relation.is_contact)return {success:false,not_submitted:true,already_friend:true,user_id:target.user_id,error_message:'Searched user is already a native contact'};
 if(!target.ticket)return {success:false,not_submitted:true,user_id:target.user_id,error_message:'Native search returned no friend verification ticket'};
 const service=requestShared(0x6fecd28,[requestSession()]);if(service.isNull())throw new Error('No native verification service');
 requestValidate(0x66e20ec,[0xa9ba7bfd,0xa9016ffc,0xa90267fa,0xa9035ff8]);
 const result=requestVerify(0x66e20ec,['pointer','pointer','pointer','uint','uint','pointer','pointer','pointer','pointer','pointer'],
  [service,requestString(target.user_id),requestString(''),0,0,requestString(target.ticket),
   requestString(parameters.greeting||''),requestString(''),requestString(parameters.remark||''),requestString('')]);
 return Object.assign(result,{user_id:target.user_id,source:'native_verifyuser'});
}
function requestDispatch(parameters){
 if(parameters.operation==='list_friend_requests'){
  const rows=requestRecords(),offset=parameters.offset||0,limit=parameters.limit;const selected=limit===0||limit===null?rows.slice(offset):rows.slice(offset,offset+limit);
  return {success:true,requests:selected.map(row=>requestPublic(row,parameters.include_contact_status!==false)),total:rows.length,offset,returned:selected.length,has_more:offset+selected.length<rows.length,source:'local_native_fmessage'};
 }
 if(parameters.operation==='search_new_contact'){try{const target=requestSearch(parameters.query);target.verification_ticket_available=!!target.ticket;delete target.ticket;return {success:target.success,target:target,source:'native_searchcontact'};}catch(error){return {success:false,error_message:String(error),stage:requestState.stage,source:'native_searchcontact'};}}
 if(parameters.operation==='accept_friend_request')return requestAccept(parameters);
 if(parameters.operation==='add_friend')return requestAdd(parameters);
 throw new Error('Unsupported friend-request operation');
}
rpc.exports={prepare(expectedTid,parameters){
 if(requestState.prepared)throw new Error('Friend-request task already prepared');
 if(Process.arch!=='arm64'||!Number.isInteger(expectedTid)||expectedTid<=0)throw new Error('Expected ARM64 executor TID');
 requestKeep.main=Process.getModuleByName('wechat');requestKeep.shared=[];
 requestValidate(0x6089d34,[0xd101c3ff,0xa9057bfd,0xa9064ff4,0x910143fd]);
 const helper=bridgeKeepalive.module.enumerateSymbols().find(s=>s.name==='rh_post_x8');
 if(!helper||helper.address.readU32()!==0xaa0403e8||helper.address.add(4).readU32()!==0xd61f00a0)throw new Error('Native sret bridge unavailable');
 requestKeep.sret=new NativeFunction(helper.address,'void',Array(6).fill('pointer'));requestKeep.release=requestNative(0x735c25c,'void',['pointer']);
 requestKeep.task=new NativeCallback(()=>{
  if(requestState.invoked)return;requestState.invoked=true;requestState.invocationCount++;
  try{if(Process.getCurrentThreadId()!==expectedTid)throw new Error('Unexpected friend-request executor thread');const result=requestDispatch(parameters);send({kind:'friend_request_result',result,error:''});requestState.completionCount++;}
  catch(error){requestState.errors.push({where:'friend_request',message:String(error)});}
  finally{for(const shared of requestKeep.shared.reverse())requestKeep.release(shared);requestState.completed=true;requestState.destroyed=true;}
 },'void',['pointer']);requestState.prepared=true;return requestKeep.task.toString();
},status(){return Object.assign({},requestState);}};
