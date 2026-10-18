'use strict';
// Bound to the researched build. Calls run on the existing executor thread.
const groupState = {prepared:false,invoked:false,completed:false,destroyed:false,
  invocationCount:0,completionCount:0,errors:[]};
const groupKeep = {};
function groupReadString(p) {
  const flag=p.readU8();
  const n=(flag&1)?p.add(8).readU64().toNumber():flag>>>1;
  if (!(flag&1) && n>22) throw new Error('Invalid native short string');
  const data=(flag&1)?p.add(16).readPointer():p.add(1);
  return n===0?'':data.readUtf8String(n);
}
function groupString(value) {
  const data=Memory.allocUtf8String(value);
  const bytes=unescape(encodeURIComponent(value)).length;
  const p=Memory.alloc(24);p.writeByteArray(new Uint8Array(24));
  if(bytes<=22){p.writeU8(bytes*2);p.add(1).writeUtf8String(value);}
  else {p.writeU64(uint64(bytes+1).or(1));p.add(8).writeU64(bytes);p.add(16).writePointer(data);}
  groupKeep.strings.push(data,p);return p;
}
function groupValidate(offset, expected) {
  const p=groupKeep.main.base.add(offset);
  for(let i=0;i<expected.length;i++) if(p.add(i*4).readU32()!==expected[i])
    throw new Error('Group entry prologue mismatch at '+offset.toString(16));
  return p;
}
function groupNative(offset,ret,args){return new NativeFunction(groupKeep.main.base.add(offset),ret,args);}
function groupSret(offset,output,args=[]) {
  const values=args.slice();while(values.length<4)values.push(ptr(0));
  groupKeep.sret(...values,output,groupKeep.main.base.add(offset));
}
function groupShared(offset,args=[]) {
  const out=Memory.alloc(16);out.writeByteArray(new Uint8Array(16));
  groupSret(offset,out,args);groupKeep.shared.push(out);return out.readPointer();
}
function groupService() {
  const context=groupShared(0x5eee0b4);
  if(context.isNull())throw new Error('No logged-in context');
  const session=groupShared(0x602cd40,[context]);
  const service=groupShared(0x5f3c6a8,[session]);
  if(service.isNull())throw new Error('No native group service');
  return service;
}
function groupMembers(groupId,refresh) {
  const service=groupService();
  if(refresh) {
    groupValidate(0x7581624,[0xa9bb7bfd,0xa90167fc,0xa9025ff8,0xa90357f6]);
    const result=groupNativeSubmit(0x7581d10,()=>{
      groupNative(0x7581624,'void',['pointer','pointer','pointer','uint'])(service,groupString(groupId),ptr(0),0);
      return true;
    });
    if(result.native_error_type!==0||result.native_error_code!==0)return Object.assign(result,{success:false,error_message:'Native group member refresh did not complete'});
  }
  const record=groupShared(0x7587a88,[service,groupString(groupId)]);
  if(record.isNull())return {success:false,error_message:'Group is absent from the local cache'};
  const owner=groupReadString(record.add(0x20));
  const adminCount=record.add(0x88).readS32();
  const admins=new Set();
  const adminList=record.add(0x80).readPointer();
  if(adminCount<0||(adminCount>0&&adminList.isNull()))throw new Error('Invalid administrator list');
  for(let i=0;i<adminCount;i++)admins.add(groupReadString(adminList.add(i*8).readPointer()));
  const count=record.add(0xd8).readU64().toNumber();
  let node=record.add(0xd0).readPointer();
  const members=[];const visited=new Set();
  while(!node.isNull()) {
    if(visited.has(node.toString())||members.length>=count)throw new Error('Invalid native member map');
    visited.add(node.toString());
    const id=groupReadString(node.add(0x10));
    const detail=node.add(0x28).readPointer();
    const flags=detail.isNull()?null:detail.add(0x20).readU32();
    members.push({member_id:id,is_owner:id===owner,is_admin:admins.has(id),
      role:id===owner?'owner':admins.has(id)?'admin':'member',native_member_flag:flags});
    node=node.readPointer();
  }
  if(members.length!==count)throw new Error('Native member map count mismatch');
  const app=groupNative(0x5eed288,'pointer',[])();
  const getSelf=new NativeFunction(app.readPointer().add(0x28).readPointer(),'pointer',['pointer']);
  const selfId=groupReadString(getSelf(app));
  const selfRole=selfId===owner?'owner':admins.has(selfId)?'admin':members.some(m=>m.member_id===selfId)?'member':'unknown';
  return {success:true,group_id:groupId,owner_id:owner,members:members,
    member_count:count,self_id:selfId,self_role:selfRole,member_version:record.add(0x7c).readU32(),source:refresh?'native_refreshed':'local_native_cache'};
}
function groupInfo(groupId,refresh) {
  const service=groupService();
  let refreshed=false;
  if(refresh) {
    groupValidate(0x75804ec,[0xa9bc7bfd,0xa9015ffc,0xa90257f6,0xa9034ff4]);
    const tid=Process.getCurrentThreadId();
    const update=Interceptor.attach(groupKeep.main.base.add(0x7581094),{onEnter(args){
      if(Process.getCurrentThreadId()===tid&&args[0].equals(service)&&
          this.returnAddress.equals(groupKeep.main.base.add(0x7580814)))refreshed=true;
    }});
    Interceptor.flush();
    try {groupNative(0x75804ec,'void',['pointer','pointer'])(service,groupString(groupId));}
    finally {update.detach();}
  }
  const record=groupShared(0x7580a00,[service,groupString(groupId)]);
  if(record.isNull())return {success:false,error_message:'No local group information'};
  if(groupReadString(record.add(8))!==groupId)throw new Error('Native group information ID mismatch');
  const context=groupShared(0x5eee0b4);
  const session=groupShared(0x602cd40,[context]);
  const contacts=groupShared(0x5faa590,[session]);
  const contact=groupShared(0x7547d4c,[contacts,groupString(groupId)]);
  const approval=contact.isNull()?null:contact.add(0x158).readU32();
  return {success:true,group_id:groupId,invitation_confirmation_status:approval,invitation_confirmation:approval===0?false:approval===2?true:null,announcement:groupReadString(record.add(0x20)),
    announcement_editor:groupReadString(record.add(0x38)),
    announcement_publish_time:record.add(0x50).readU64().toString(),
    announcement_xml:groupReadString(record.add(0x60)),source:refreshed?'native_refreshed':'local_native_cache',refresh_requested:refresh,refresh_complete:refreshed};
}
function groupVector(ids) {
  const storage=Memory.alloc(Math.max(ids.length*24,1));
  for(let i=0;i<ids.length;i++)storage.add(i*24).writeByteArray(groupString(ids[i]).readByteArray(24));
  const vector=Memory.alloc(24);vector.writePointer(storage);
  vector.add(8).writePointer(storage.add(ids.length*24));vector.add(16).writePointer(storage.add(ids.length*24));
  groupKeep.strings.push(storage,vector);return vector;
}
function groupCreate(parameters) {
  groupValidate(0x75938d0,[0xa9ba7bfd,0xa9016ffc,0xa90267fa,0xa9035ff8]);
  const service=groupService();const output=Memory.alloc(24);output.writeByteArray(new Uint8Array(24));
  groupSret(0x75938d0,output,[service,groupVector(parameters.member_ids),groupString(parameters.name)]);
  const id=groupReadString(output);
  if(output.readU8()&1)groupNative(0x4499070,'void',['pointer'])(output.add(16).readPointer());
  return {success:!!id,group_id:id||null,error_message:id?'':'Native create-group operation returned no group ID'};
}
function groupInvite(parameters) {
  const offset=parameters.mode==='invite'?0x75991ac:0x7591ad0;
  groupValidate(offset,[0xa9ba7bfd,0xa9016ffc,0xa90267fa,0xa9035ff8]);
  const service=groupService();const history=Memory.alloc(0x50);
  groupNative(0x788d22c,'void',['pointer'])(history);
  let result;
  try {
    const args=[service,groupVector(parameters.member_ids),groupString(parameters.group_id),history];
    if(parameters.mode==='add')args.push(groupString(''));
    result=groupNativeSubmit(parameters.mode==='add'?0x7592410:0x759a0b4,
      ()=>!!groupNative(offset,'bool',Array(args.length).fill('pointer'))(...args));
  } finally {groupNative(0x788d2b4,'void',['pointer'])(history);}
  return Object.assign(result,{group_id:parameters.group_id,mode:parameters.mode,
    membership_confirmed:false,error_message:result.success?'':'Native group member operation returned false'});
}
function groupRemoveMembers(parameters) {
  groupValidate(0x7597504,[0xa9ba7bfd,0xa9016ffc,0xa90267fa,0xa9035ff8]);
  const service=groupService();
  // The standard member-selection UI uses scene0. Return is pair<bool,string>, not a bool.
  const output=Memory.alloc(0x20);output.writeByteArray(new Uint8Array(0x20));
  let result;
  try {
    result=groupNativeSubmit(0x7598a6c,()=>{
      groupSret(0x7597504,output,[service,groupVector(parameters.member_ids),
                               groupString(parameters.group_id),ptr(0)]);
      return output.readU8()!==0;
    });
    const message=groupReadString(output.add(8));
    return Object.assign(result,{group_id:parameters.group_id,member_ids:parameters.member_ids,
      error_message:result.success?'':message||'Native remove-members operation returned false'});
  } finally {
    const message=output.add(8);
    if(message.readU8()&1)groupNative(0x4499070,'void',['pointer'])(message.add(16).readPointer());
  }
}
function groupOwnedString(offset,args) {
  const out=Memory.alloc(24);out.writeByteArray(new Uint8Array(24));
  groupSret(offset,out,args);const text=groupReadString(out);
  if(out.readU8()&1)groupNative(0x4499070,'void',['pointer'])(out.add(16).readPointer());
  return text;
}
function groupSelfId() {
  const app=groupNative(0x5eed288,'pointer',[])();
  return groupReadString(new NativeFunction(app.readPointer().add(0x28).readPointer(),'pointer',['pointer'])(app));
}
function groupNativeSubmit(offset,callback) {
  let codes=null;const tid=Process.getCurrentThreadId();
  const handle=Interceptor.attach(groupKeep.main.base.add(offset),{
    onEnter(args){if(Process.getCurrentThreadId()===tid)this.output=this.context.x8;},
    onLeave(retval){
      if(!this.output)return;
      codes={native_error_type:this.output.readS32(),native_error_code:this.output.add(4).readS32()};
      if(offset===0x75cb314) {
        codes.native_error_message=groupReadString(this.output.add(8));
        const response=this.output.add(0x20).readPointer();
        codes.native_item_errors=[];
        if(!response.isNull()) {
          const list=response.add(8).readPointer();
          if(!list.isNull()) {
            const count=list.add(0x10).readS32();
            if(count<0)throw new Error('Invalid native oplog result count');
            const items=list.add(8).readPointer();
            for(let i=0;i<count;i++)codes.native_item_errors.push(items.add(i*4).readS32());
          }
        }
      }
    }
  });
  Interceptor.flush();
  try {return Object.assign({success:!!callback()},codes||{});}
  finally {handle.detach();}
}
function groupAnnouncement(parameters,preview) {
  if(parameters.clear&&!preview) {
    groupValidate(0x724ecb0,[0xa9bd7bfd,0xa90157fc,0xa9024ff4,0x910003fd]);
    const result=groupNativeSubmit(0x724e570,()=>groupNative(0x724ecb0,'bool',['pointer'])(groupString(parameters.group_id)));
    return Object.assign(result,{group_id:parameters.group_id,error_message:result.success?'':'Native announcement clear returned false'});
  }
  groupValidate(0x664c730,[0xa9be7bfd,0xa9014ff4,0x910003fd,0x6f00e400]);
  groupValidate(0x724de4c,[0xa9ba7bfd,0xf9000bfc,0xa90267fa,0xa9035ff8]);
  const object=Memory.alloc(0x68);object.writeByteArray(new Uint8Array(0x68));
  groupNative(0x664c730,'void',['pointer','pointer'])(object,groupString(parameters.xml));
  try {
    const groupId=groupReadString(object.add(0x20));
    if(groupId!==parameters.group_id)throw new Error('Parsed announcement group ID mismatch');
    const text=groupOwnedString(0x664cea8,[object,ptr(0)]);
    if(parameters.text!==undefined&&text!==parameters.text)throw new Error('Native announcement text roundtrip mismatch');
    if(preview)return {success:true,text:text,xml:groupOwnedString(0x664d228,[object])};
    // Use the same native metadata constructor as the client editor.
    const metadata=Memory.alloc(0x68);metadata.writeByteArray(new Uint8Array(0x68));
    groupValidate(0x725045c,[0xd102c3ff,0xa9087bfd,0xf9004bf5,0xa90a4ff4]);
    groupSret(0x725045c,metadata,[groupString(parameters.group_id)]);
    try {
      object.writeU64(metadata.readU64());
      const assign=groupNative(0x449cf38,'void',['pointer','pointer']);
      assign(object.add(8),metadata.add(8));
      assign(object.add(0x38),metadata.add(0x38));
    } finally {groupNative(0x664c8e8,'void',['pointer'])(metadata);}
    const result=groupNativeSubmit(0x724e570,()=>groupNative(0x724de4c,'bool',['pointer'])(object));
    return Object.assign(result,{group_id:groupId,error_message:result.success?'':'Native announcement publish returned false'});
  } finally {groupNative(0x664c8e8,'void',['pointer'])(object);}
}
function groupPin(parameters,preview) {
  groupValidate(0x632e5f0,[0xa9bb7bfd,0xf9000bfc,0xa9025ff8,0xa90357f6]);
  groupValidate(0x5f09904,[0xd10203ff,0xa9027bfd,0xf9001bfb,0xa90467fa]);
  groupValidate(0x695c014,[0xa9bc7bfd,0xf9000bfc,0xa90257f6,0xa9034ff4]);
  const context=groupShared(0x5eee0b4);
  const session=groupShared(0x602cd40,[context]);
  const service=groupShared(0x6db61c0,[session]);
  const id=uint64(parameters.message_id);const group=groupString(parameters.group_id);
  if(!parameters.pinned&&!preview) {
    const result=groupNativeSubmit(0x695b8d0,()=>!!groupNative(0x695b554,'bool',['pointer','pointer','uint64'])(service,group,id));
    return Object.assign(result,{group_id:parameters.group_id,message_id:parameters.message_id,pinned:false,
      error_message:result.success?'':'Native unpin returned false'});
  }
  const manager=groupShared(0x603c2a4,[session]);
  const message=Memory.alloc(0x280);message.writeByteArray(new Uint8Array(0x280));
  groupSret(0x632e5f0,message,[manager,group,ptr('0x'+id.toString(16))]);
  if(message.add(0x278).readU8()===0)return {success:false,error_message:'Server message ID is absent from this group local history'};
  const view=Memory.alloc(0x350);let constructed=false;
  try {
    if(message.add(0xf8).readU64().compare(id)!==0)throw new Error('Native message server ID mismatch');
    groupSret(0x5f09904,view,[message]);constructed=true;
    if(groupReadString(view.add(0x58))!==parameters.group_id||view.add(0x90).readU64().compare(id)!==0)throw new Error('Native message view identity mismatch');
    if(preview)return {success:true,group_id:parameters.group_id,message_id:parameters.message_id,
      message_type:view.add(8).readU32(),native_view:true};
    const result=groupNativeSubmit(0x695b8d0,()=>!!groupNative(0x695c014,'bool',['pointer','pointer'])(service,view));
    return Object.assign(result,{group_id:parameters.group_id,message_id:parameters.message_id,pinned:true,
      error_message:result.success?'':'Native pin returned false'});
  } finally {
    if(constructed)groupNative(0x46b4fc0,'void',['pointer'])(view);
    new NativeFunction(message.readPointer().readPointer(),'void',['pointer'])(message);
  }
}
function groupWireString(hex) {
  const bytes=[];for(let i=0;i<hex.length;i+=2)bytes.push(parseInt(hex.slice(i,i+2),16));
  const out=Memory.alloc(24);out.writeByteArray(new Uint8Array(24));
  const data=Memory.alloc(bytes.length+1);data.writeByteArray(bytes);data.add(bytes.length).writeU8(0);
  if(bytes.length<=22){out.writeU8(bytes.length*2);out.add(1).writeByteArray(bytes);}
  else {out.writeU64(uint64(Math.ceil((bytes.length+1)/16)*16).or(1));out.add(8).writeU64(bytes.length);out.add(16).writePointer(data);}
  groupKeep.strings.push(out,data);return out;
}
function groupApproval(parameters) {
  groupValidate(0x75c8fcc,[0xa9bb7bfd,0xf9000bfc,0xa9025ff8,0xa90357f6]);
  groupValidate(0x75cb314,[0xfc190fe8,0xa9017bfd,0xa9026ffc,0xa90367fa]);
  const context=groupShared(0x5eee0b4);
  const session=groupShared(0x602cd40,[context]);
  // Oplog has a different native service receiver from member operations.
  groupValidate(0x603d064,[0xd101c3ff,0xa9057bfd,0xa9064ff4,0x910143fd]);
  const service=groupShared(0x603d064,[session]);
  if(service.isNull())throw new Error('No native chatroom settings service');
  const result=groupNativeSubmit(0x75cb314,()=>{
    groupNative(0x75c8fcc,'void',['pointer','pointer','uint'])(service,groupWireString(parameters.payload_hex),66);
    return true;
  });
  const complete=result.native_error_type!==undefined&&result.native_error_code!==undefined&&result.native_item_errors&&result.native_item_errors.length>0;
  result.success=!!(complete&&result.native_error_type===0&&result.native_error_code===0&&result.native_item_errors.every(v=>v===0));
  result.submission_unknown=!complete;
  result.group_id=parameters.group_id;result.enabled=parameters.enabled;
  result.error_message=result.success?'':complete?'Native invitation-confirmation oplog returned an error':'Native oplog completion not established';
  return result;
}
function groupDispatch(parameters) {
  if(parameters.operation==='get_group_members')return groupMembers(parameters.group_id,parameters.refresh);
  if(parameters.operation==='get_group_info')return groupInfo(parameters.group_id,parameters.refresh);
  if(parameters.operation==='create_group')return groupCreate(parameters);
  if(parameters.operation==='invite_group_members')return groupInvite(parameters);
  if(parameters.operation==='remove_group_members')return groupRemoveMembers(parameters);
  if(parameters.operation==='preview_group_announcement')return groupAnnouncement(parameters,true);
  if(parameters.operation==='set_group_announcement')return groupAnnouncement(parameters,false);
  if(parameters.operation==='preview_group_pin')return groupPin(parameters,true);
  if(parameters.operation==='pin_group_message')return groupPin(parameters,false);
  if(parameters.operation==='set_group_invitation_confirmation')return groupApproval(parameters);
  throw new Error('Unsupported group operation');
}
rpc.exports={
  prepare(expectedTid,parameters) {
    if(groupState.prepared)throw new Error('Group task already prepared');
    if(Process.arch!=='arm64'||!Number.isInteger(expectedTid)||expectedTid<=0)throw new Error('Expected ARM64 executor TID');
    if(!['get_group_members','get_group_info','create_group','invite_group_members','remove_group_members','preview_group_announcement','set_group_announcement','preview_group_pin','pin_group_message','set_group_invitation_confirmation'].includes(parameters.operation))throw new Error('Unsupported group operation');
    groupKeep.main=Process.getModuleByName('wechat');
    groupKeep.strings=[];groupKeep.shared=[];
    groupValidate(0x5eee0b4,[0xd100c3ff,0xa9017bfd,0xf90013f3,0x910043fd]);
    groupValidate(0x7587a88,[0xa9ba7bfd,0xa9016ffc,0xa90267fa,0xa9035ff8]);
    const symbols=bridgeKeepalive.module.enumerateSymbols();
    const helper=symbols.find(s=>s.name==='rh_post_x8');
    if(!helper||helper.address.readU32()!==0xaa0403e8||helper.address.add(4).readU32()!==0xd61f00a0)throw new Error('Native sret bridge unavailable');
    groupKeep.sret=new NativeFunction(helper.address,'void',Array(6).fill('pointer'));
    groupKeep.release=groupNative(0x735c25c,'void',['pointer']);
    groupKeep.task=new NativeCallback(userdata=>{
      if(groupState.invoked)return;
      groupState.invoked=true;groupState.invocationCount++;
      try {
        if(Process.getCurrentThreadId()!==expectedTid)throw new Error('Unexpected group executor thread');
        const result=groupDispatch(parameters);
        send({kind:'group_result',result:result,error:''});
        groupState.completionCount++;
      } catch(error){groupState.errors.push({where:'group',message:String(error)});}
      finally {
        for(const shared of groupKeep.shared.reverse())groupKeep.release(shared);
        groupState.completed=true;groupState.destroyed=true;
      }
    },'void',['pointer']);
    groupState.prepared=true;return groupKeep.task.toString();
  },
  status(){return Object.assign({},groupState);}
};
