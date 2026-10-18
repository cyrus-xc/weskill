'use strict';
// Native contact-service route for the researched Linux WeChat build.
const remarkState={prepared:false,invoked:false,completed:false,destroyed:false,
  invocationCount:0,completionCount:0,errors:[]};
const remarkKeep={strings:[],shared:[]};
function remarkValidate(offset,words){
  const p=remarkKeep.main.base.add(offset);
  words.forEach((word,i)=>{if(p.add(i*4).readU32()!==word)
    throw new Error('Contact remark entry mismatch at '+offset.toString(16));});
  return p;
}
function remarkNative(offset,ret,args){return new NativeFunction(remarkKeep.main.base.add(offset),ret,args);}
function remarkReadString(p){
  const flag=p.readU8(),n=(flag&1)?p.add(8).readU64().toNumber():flag>>>1;
  if(!(flag&1)&&n>22)throw new Error('Invalid contact remark short string');
  return n===0?'':((flag&1)?p.add(16).readPointer():p.add(1)).readUtf8String(n);
}
function remarkString(text){
  const bytes=unescape(encodeURIComponent(text)).length;
  const data=Memory.allocUtf8String(text),out=Memory.alloc(24);
  out.writeByteArray(new Uint8Array(24));
  if(bytes<=22){out.writeU8(bytes*2);out.add(1).writeUtf8String(text);}
  else{out.writeU64(uint64(Math.ceil((bytes+1)/16)*16).or(1));out.add(8).writeU64(bytes);out.add(16).writePointer(data);}
  remarkKeep.strings.push(data,out);return out;
}
function remarkShared(offset,args=[]){
  const out=Memory.alloc(16);out.writeByteArray(new Uint8Array(16));
  const values=args.slice();while(values.length<4)values.push(ptr(0));
  remarkKeep.sret(...values,out,remarkKeep.main.base.add(offset));
  remarkKeep.shared.push(out);return out.readPointer();
}
function remarkDispatch(parameters){
  const context=remarkShared(0x5eee0b4);
  if(context.isNull())throw new Error('No logged-in context');
  const session=remarkShared(0x602cd40,[context]);
  if(session.isNull())throw new Error('No logged-in session');
  const contacts=remarkShared(0x5faa590,[session]);
  if(contacts.isNull())throw new Error('No native contact service');
  const id=remarkString(parameters.contact_id),value=remarkString(parameters.remark);
  const contact=remarkShared(0x7547d4c,[contacts,id]);
  if(contact.isNull())return {success:false,not_submitted:true,contact_id:parameters.contact_id,
    error_message:'Contact is absent from the local native cache'};
  const tid=Process.getCurrentThreadId(),completions=[];
  // Standard ModContact oplog and the dedicated SetRemark oplog both wait for
  // the network result. Read borrowed result strings before native teardown.
  const hooks=[0x75cb314,0x75d7424].map(offset=>Interceptor.attach(remarkKeep.main.base.add(offset),{
    onEnter(args){if(Process.getCurrentThreadId()===tid)this.output=this.context.x8;},
    onLeave(){
      if(!this.output)return;
      const result={native_error_type:this.output.readS32(),native_error_code:this.output.add(4).readS32(),
        native_error_message:remarkReadString(this.output.add(8))};
      if(offset===0x75cb314){
        result.native_item_errors=[];
        const response=this.output.add(0x20).readPointer();
        if(!response.isNull()){
          const list=response.add(8).readPointer();
          if(!list.isNull()){
            const count=list.add(0x10).readS32(),items=list.add(8).readPointer();
            if(count<0||(count>0&&items.isNull()))throw new Error('Invalid contact oplog results');
            for(let i=0;i<count;i++)result.native_item_errors.push(items.add(i*4).readS32());
          }
        }
      }
      completions.push(result);
    }
  }));
  Interceptor.flush();
  try{remarkNative(0x755c308,'void',['pointer','pointer','pointer'])(contacts,id,value);}
  finally{hooks.forEach(h=>h.detach());Interceptor.flush();}
  const complete=completions.length>0&&completions.every(c=>
    c.native_error_type!==0||c.native_error_code!==0||
    c.native_item_errors===undefined||c.native_item_errors.length>0);
  const success=complete&&completions.every(c=>c.native_error_type===0&&c.native_error_code===0&&
    (c.native_item_errors===undefined||c.native_item_errors.every(code=>code===0)));
  return Object.assign({},completions[completions.length-1]||{},
    {success:success,submission_unknown:!complete,contact_id:parameters.contact_id,remark:parameters.remark,
      error_message:success?'':complete?'Native contact remark operation returned an error':'Native contact remark completion not established'});
}
rpc.exports={
  prepare(expectedTid,parameters){
    if(remarkState.prepared)throw new Error('Contact remark task already prepared');
    if(Process.arch!=='arm64'||!Number.isInteger(expectedTid)||expectedTid<=0)throw new Error('Expected ARM64 executor TID');
    if(!parameters||typeof parameters.contact_id!=='string'||parameters.contact_id.length===0||
        parameters.contact_id.includes('\0')||typeof parameters.remark!=='string'||parameters.remark.includes('\0'))
      throw new Error('Invalid contact remark parameters');
    remarkKeep.main=Process.getModuleByName('wechat');
    remarkValidate(0x5eee0b4,[0xd100c3ff,0xa9017bfd,0xf90013f3,0x910043fd]);
    remarkValidate(0x602cd40,[0xa942a40a,0xa900250a,0xb40000c9,0x91002128]);
    remarkValidate(0x5faa590,[0xd101c3ff,0xa9057bfd,0xa9064ff4,0x910143fd]);
    remarkValidate(0x7547d4c,[0xa9bb7bfd,0xf9000bfc,0xa9025ff8,0xa90357f6]);
    remarkValidate(0x755c308,[0xa9bc7bfd,0xa9015ffc,0xa90257f6,0xa9034ff4]);
    remarkValidate(0x75cb314,[0xfc190fe8,0xa9017bfd,0xa9026ffc,0xa90367fa]);
    remarkValidate(0x75d7424,[0xfc190fe8,0xa9017bfd,0xa9026ffc,0xa90367fa]);
    const helper=bridgeKeepalive.module.enumerateSymbols().find(s=>s.name==='rh_post_x8');
    if(!helper||helper.address.readU32()!==0xaa0403e8||helper.address.add(4).readU32()!==0xd61f00a0)
      throw new Error('Native sret bridge unavailable');
    remarkKeep.sret=new NativeFunction(helper.address,'void',Array(6).fill('pointer'));
    remarkKeep.release=remarkNative(0x735c25c,'void',['pointer']);
    remarkKeep.task=new NativeCallback(userdata=>{
      if(remarkState.invoked)return;
      remarkState.invoked=true;remarkState.invocationCount++;
      try{
        if(Process.getCurrentThreadId()!==expectedTid)throw new Error('Unexpected contact remark executor thread');
        const result=remarkDispatch(parameters);
        send({kind:'friend_remark_result',result:result,error:''});remarkState.completionCount++;
      }catch(error){remarkState.errors.push({where:'friend_remark',message:String(error)});}
      finally{
        for(const shared of remarkKeep.shared.reverse())remarkKeep.release(shared);
        remarkState.completed=true;remarkState.destroyed=true;
      }
    },'void',['pointer']);
    remarkState.prepared=true;return remarkKeep.task.toString();
  },
  status(){return Object.assign({},remarkState);}
};
