'use strict';
// Reuse the genuine native DataInfo message construction used by the UI.
// The executor invokes once; this code does not access or manipulate any widget.
const emojiState={prepared:false,invoked:false,completed:false,destroyed:false,
 invocationCount:0,completionCount:0,errors:[]};
const emojiKeep={strings:[],shared:[]};
function emojiValidate(offset,words){const p=emojiKeep.main.base.add(offset);words.forEach((w,i)=>{if(p.add(i*4).readU32()!==w)throw new Error('Sticker entry mismatch at '+offset.toString(16));});return p;}
function emojiNative(offset,ret,args){return new NativeFunction(emojiKeep.main.base.add(offset),ret,args);}
function emojiRead(p){if(p.isNull())throw new Error('Missing native sticker string');const flag=p.readU8(),n=(flag&1)?p.add(8).readU64().toNumber():flag>>>1;if(!(flag&1)&&n>22)throw new Error('Invalid native sticker short string');if(!Number.isSafeInteger(n)||n<0)throw new Error('Invalid native sticker string length');return n?((flag&1)?p.add(16).readPointer():p.add(1)).readUtf8String(n):'';}
function emojiString(value){const p=Memory.alloc(24),data=Memory.allocUtf8String(value),n=unescape(encodeURIComponent(value)).length;p.writeByteArray(new Uint8Array(24));if(n<=22){p.writeU8(n*2);p.add(1).writeUtf8String(value);}else{p.writeU64(uint64(Math.ceil((n+1)/16)*16).or(1));p.add(8).writeU64(n);p.add(16).writePointer(data);}emojiKeep.strings.push(p,data);return p;}
function emojiSret(offset,out,args=[]){const values=args.slice();while(values.length<4)values.push(ptr(0));emojiKeep.sret(...values,out,emojiKeep.main.base.add(offset));}
function emojiShared(offset,args=[]){const out=Memory.alloc(16);out.writeByteArray(new Uint8Array(16));emojiSret(offset,out,args);emojiKeep.shared.push(out);return out.readPointer();}
function emojiService(){const context=emojiShared(0x5eee0b4);if(context.isNull())throw new Error('No logged-in context');const session=emojiShared(0x602cd40,[context]);if(session.isNull())throw new Error('No logged-in session');const service=emojiShared(0x603c614,[session]);if(service.isNull())throw new Error('No native sticker service');return service;}

// Shared16 copy primitive 455b6c4 copies from x1 to x8 and increments the
// native control block with the same atomic operation as the UI send path.
function emojiSelect(parameters,service){
 let vector,out=null,request=null;
 if(parameters.source==='saved'){
  const category=emojiShared(0x6565fdc,[service]);
  if(category.isNull())return null;
  vector=category.add(0x68);
 }else{
  request=Memory.alloc(0x1c0);request.writeByteArray(new Uint8Array(0x1c0));
  emojiNative(0x4fd044c,'void',['pointer'])(request);
  out=Memory.alloc(0x40);out.writeByteArray(new Uint8Array(0x40));
  try{
   emojiNative(0x449cf38,'void',['pointer','pointer'])(request.add(8),emojiString(parameters.keyword));
   const cursor=parameters.native_cursor||0;request.writeU32(cursor);request.add(0xa0).writeU32(cursor);
   emojiSret(0x65697cc,out,[service,request]);
   emojiKeep.searchResult=out;
   if(out.add(0x1c).readS32()!==0)throw new Error('Native sticker search failed');
   vector=out.add(0x28);
  }finally{emojiNative(0x6ea8fe0,'void',['pointer'])(request);}
 }
 const begin=vector.readPointer(),end=vector.add(8).readPointer(),bytes=end.sub(begin).toInt32();
 if(bytes<0||bytes%16)throw new Error('Invalid native sticker vector');
 for(let i=0;i<bytes;i+=16){const shared=begin.add(i),record=shared.readPointer();if(!record.isNull()&&emojiRead(record.add(0x10))===parameters.sticker_id)return shared;}
 return null;
}
function emojiExpectedSearchPath(record){
 if(!record.readPointer().add(0x68).readPointer().equals(emojiKeep.main.base.add(0x6637544)))throw new Error('Unexpected native search path getter');
 const path=Memory.alloc(24);path.writeByteArray(new Uint8Array(24));
 emojiSret(0x6637544,path,[record]);
 try{return emojiRead(path);}finally{emojiNative(0x44c6c5c,'void',['pointer'])(path);}
}
// Same search-to-DataInfo construction as UI 4f88460 and native search
// adapter 6ea86c4. The native subtype number is preserved by its constructor.
function emojiSearchData(selected,service){
 const image=Memory.alloc(16);image.writeByteArray(new Uint8Array(16));
 emojiSret(0x6566840,image,[service,selected]);emojiKeep.shared.push(image);
 if(image.readPointer().isNull())return null;
 const block=emojiNative(0x9fa44e8,'pointer',['ulong'])(0x190);
 block.writePointer(emojiKeep.main.base.add(0xa444208).readPointer().add(0x10));
 block.add(8).writeU64(0);block.add(0x10).writeU64(0);
 const data=block.add(0x18);
 emojiNative(0x6636244,'void',['pointer','pointer'])(data,selected.readPointer());
 const owned=Memory.alloc(16);owned.writePointer(data);owned.add(8).writePointer(block);emojiKeep.shared.push(owned);
 if(!data.readPointer().equals(emojiKeep.main.base.add(0xa21c618)))throw new Error('Unexpected converted sticker DataInfo vtable');
 emojiSret(0x455b6c4,data.add(0x168),[ptr(0),image]);
 return {selected:owned,image};
}
function emojiSend(parameters){
 const service=emojiService();let selected=emojiSelect(parameters,service),searchData=null;
 if(!selected)return {success:false,not_submitted:true,error_message:'Selected sticker is no longer in its native source'};
 const nativeType=selected.readPointer().add(8).readS32();
 if(parameters.source==='search'){
  if(nativeType!==6)return {success:false,not_submitted:true,native_type:nativeType,error_message:'Unsupported native search sticker type'};
  searchData=emojiSearchData(selected,service);
  if(!searchData){const requested=!!emojiNative(0x6566cb8,'uint',['pointer','pointer','uint'])(service,selected,0);return {success:false,not_submitted:true,material_pending:true,download_requested:requested,expected_local_path:emojiExpectedSearchPath(selected.readPointer()),error_message:'Native sticker download is pending; no message has been submitted'};}
  selected=searchData.selected;
 }else if(nativeType!==3&&nativeType!==5)return {success:false,not_submitted:true,native_type:nativeType,error_message:'Selected sticker has no verified native DataInfo send conversion'};
 const context=emojiShared(0x5eee0b4),session=emojiShared(0x602cd40,[context]),manager=emojiShared(0x603c2a4,[session]);
 if(manager.isNull())throw new Error('Native message manager unavailable');
 const messageShared=Memory.alloc(16);messageShared.writeByteArray(new Uint8Array(16));
 emojiSret(0x48e3ac4,messageShared);emojiKeep.shared.push(messageShared);
 const message=messageShared.readPointer();if(message.isNull())throw new Error('Native sticker message factory failed');
 emojiSret(0x455b6c4,message.add(0x5c8),[ptr(0),selected]);
 if(searchData)emojiSret(0x455b6c4,message.add(0x5d8),[ptr(0),searchData.image]);
 message.add(0xe4).writeU32(47);
 emojiNative(0x449cf38,'void',['pointer','pointer'])(message.add(0x90),emojiString(parameters.recipient_id));
 const result=Memory.alloc(48);result.writeByteArray(new Uint8Array(48));
 emojiKeep.submitted=true;
 emojiSret(0x6305730,result,[manager,messageShared]);
 try{
  const first=result.readS32(),second=result.add(4).readS32();
  const success=first===0&&second===0;
  let nativeKey=null;
  const key=result.add(0x20).readPointer();
  if(success&&!key.isNull()&&key.add(0x40).readU8())nativeKey=key.add(0x18).readU64().toString();
  return {success,native_error_domain:first,native_error_code:second,
   error_message:success?'':emojiRead(result.add(8)),native_message_key:nativeKey,
   sticker_id:parameters.sticker_id,source:parameters.source,native_type:nativeType,
   message_type:47,confirmation:success?'client_success':'client_rejected'};
 }finally{emojiNative(0x63064b0,'void',['pointer'])(result);}
}
rpc.exports={prepare(expectedTid,parameters){
 if(emojiState.prepared)throw new Error('Sticker send already prepared');
 if(Process.arch!=='arm64'||Process.pointerSize!==8||!Number.isInteger(expectedTid)||expectedTid<=0)throw new Error('Expected ARM64 executor TID');
 if(!parameters||!['saved','search'].includes(parameters.source))throw new Error('Expected selected sticker source');
 for(const name of ['recipient_id','sticker_id'])if(typeof parameters[name]!=='string'||!parameters[name]||parameters[name].includes('\0'))throw new Error('Expected '+name);
 if(parameters.source==='search'&&(typeof parameters.keyword!=='string'||!parameters.keyword||parameters.keyword.includes('\0')))throw new Error('Expected original sticker search keyword');
 if(parameters.native_cursor!==undefined&&(!Number.isSafeInteger(parameters.native_cursor)||parameters.native_cursor<0||parameters.native_cursor>0xffffffff))throw new Error('Expected native search cursor');
 emojiKeep.main=Process.getModuleByName('wechat');
 emojiValidate(0x6566840,[0xd101c3ff,0xa9047bfd,0xf9002bf5,0xa9064ff4]);
 emojiValidate(0x6636244,[0xd10143ff,0xa9037bfd,0xf90023f3,0x9100c3fd]);
 if(!emojiKeep.main.base.add(0xa444208).readPointer().equals(emojiKeep.main.base.add(0xa0f4800)))throw new Error('Native DataInfo shared control block mismatch');
 emojiValidate(0x48e3ac4,[0xa9be7bfd,0xa9014ff4,0x910003fd,0x5280c100]);
 emojiValidate(0x455b6c4,[0xa940242a,0xb40000c9,0x9100212b,0xc85f7d6c]);
 emojiValidate(0x6305730,[0xd100c3ff,0xa9017bfd,0xf90013f3,0x910043fd]);
 emojiValidate(0x603c2a4,[0xd101c3ff,0xa9057bfd,0xa9064ff4,0x910143fd]);
 emojiValidate(0x63064b0,[0xa9be7bfd,0xa9014ff4,0x910003fd,0xf9401413]);
 const helper=bridgeKeepalive.module.enumerateSymbols().find(s=>s.name==='rh_post_x8');if(!helper||helper.address.readU32()!==0xaa0403e8||helper.address.add(4).readU32()!==0xd61f00a0)throw new Error('Native sticker sret bridge unavailable');
 emojiKeep.sret=new NativeFunction(helper.address,'void',Array(6).fill('pointer'));emojiKeep.release=emojiNative(0x735c25c,'void',['pointer']);
 emojiKeep.task=new NativeCallback(()=>{if(emojiState.invoked)return;emojiState.invoked=true;emojiState.invocationCount++;
  try{if(Process.getCurrentThreadId()!==expectedTid)throw new Error('Unexpected sticker executor thread');const result=emojiSend(parameters);emojiState.completionCount++;send({kind:'emoji_send_result',result,error:''});}
  catch(error){emojiState.handled_error=String(error);emojiState.completionCount++;send({kind:'emoji_send_result',result:{success:false,not_submitted:!emojiKeep.submitted,submission_unknown:!!emojiKeep.submitted,confirmation:emojiKeep.submitted?'unknown':'not_submitted',error_message:String(error)},error:''});}
  finally{
   if(emojiKeep.searchResult)emojiNative(0x6569a04,'void',['pointer'])(emojiKeep.searchResult);
   for(const shared of emojiKeep.shared.reverse())emojiKeep.release(shared);
   emojiState.completed=true;emojiState.destroyed=true;
  }
 },'void',['pointer']);emojiState.prepared=true;return emojiKeep.task.toString();
},status(){return Object.assign({},emojiState);}};
