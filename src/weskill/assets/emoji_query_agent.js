'use strict';
// Read existing saved stickers and use the client's own online search. This does
// not call the add-to-favourites, remove or backup mutation entry points.
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
function emojiPath(record,expected=false){
 // Each supported slot is traced to the same native filesystem::path ABI.
 // Saved DataInfo and MD5Info override SearchInfo's path implementation.
 const slot=expected?0x68:0x70;
 const entry=record.readPointer().add(slot).readPointer();
 const offset=entry.sub(emojiKeep.main.base).toUInt32();
 const known=expected?[0x66362d0,0x6637544,0x663ac5c]:[0x66362e4,0x663754c,0x663ac68];
 if(!known.includes(offset))return '';
 const path=Memory.alloc(24);path.writeByteArray(new Uint8Array(24));
 emojiSret(offset,path,[record]);
 try{if(!expected&&!emojiNative(0x70bc694,'uint',['pointer'])(path))return '';return emojiRead(path);}
 finally{emojiNative(0x44c6c5c,'void',['pointer'])(path);}
}
function emojiMetadata(record,source){
 const result={sticker_id:emojiRead(record.add(0x10)),md5:emojiRead(record.add(0x10)),source,
  native_type:record.add(8).readS32(),native_vtable_offset:record.readPointer().sub(emojiKeep.main.base).toString(),
  native_path_getter_offsets:{expected:record.readPointer().add(0x68).readPointer().sub(emojiKeep.main.base).toString(),local:record.readPointer().add(0x70).readPointer().sub(emojiKeep.main.base).toString()},product_id:emojiRead(record.add(0x28)),
  aes_key:emojiRead(record.add(0x40)),thumb_url:emojiRead(record.add(0x58)),
  thumb_source_url:emojiRead(record.add(0x70)),thumb_aes_key:emojiRead(record.add(0x88)),
  cdn_url:emojiRead(record.add(0xa0)),encrypt_url:emojiRead(record.add(0xb8)),
  tp_auth_key:emojiRead(record.add(0xd0)),tp_url:emojiRead(record.add(0xe8)),
  extern_url:emojiRead(record.add(0x100)),extern_md5:emojiRead(record.add(0x118)),
  native_dimension_1:record.add(0x134).readS32(),native_dimension_2:record.add(0x138).readS32(),
  local_path:emojiPath(record),expected_local_path:emojiPath(record,true)};
 if(!result.md5)throw new Error('Native sticker record has no MD5');
 return result;
}
function emojiVector(vector,source,service,parameters){const begin=vector.readPointer(),end=vector.add(8).readPointer(),bytes=end.sub(begin).toInt32();if(bytes<0||bytes%16)throw new Error('Invalid native sticker vector');const rows=[];for(let i=0;i<bytes;i+=16){const record=begin.add(i).readPointer();if(record.isNull())throw new Error('Missing native sticker record');const metadata=emojiMetadata(record,source);rows.push(metadata);}return rows;}
function emojiSaved(parameters,service){const category=emojiShared(0x6565fdc,[service]);if(category.isNull())throw new Error('Saved-sticker collection unavailable');const rows=emojiVector(category.add(0x68),'saved',service,parameters),offset=parameters.offset||0,limit=parameters.limit===undefined?20:parameters.limit;const selected=limit===0||limit===null?rows.slice(offset):rows.slice(offset,offset+limit);return {success:true,stickers:selected,total:rows.length,offset,returned:selected.length,has_more:offset+selected.length<rows.length,source:'native_saved_stickers'};}
function emojiSearchPage(parameters,service){
 const request=Memory.alloc(0x1c0),out=Memory.alloc(0x40);request.writeByteArray(new Uint8Array(0x1c0));out.writeByteArray(new Uint8Array(0x40));
 // Use the real request initializer, including logged-in client data and the
 // native search defaults. assign() copies the borrowed query into owned memory.
 emojiNative(0x4fd044c,'void',['pointer'])(request);
 try{
  emojiNative(0x449cf38,'void',['pointer','pointer'])(request.add(8),emojiString(parameters.keyword));
  const cursor=parameters.native_cursor||0;
  request.writeU32(cursor);
  // UI's load-more setter 0x4fd10b8 writes both fields to total_count+1.
  request.add(0xa0).writeU32(cursor);
  emojiSret(0x65697cc,out,[service,request]);
  try{const status=out.add(0x1c).readS32();if(status!==0)return {success:false,native_status:status,error_message:'Native sticker search failed',stickers:[],has_more:false,source:'native_sticker_search'};const rows=emojiVector(out.add(0x28),'search',service,parameters);const cursor=out.add(0x18).readU32(),hasMore=!!out.add(0x20).readU8();return {success:true,stickers:rows,native_cursor:cursor,next_native_cursor:hasMore?(cursor===0?rows.length+1:cursor+rows.length):null,returned:rows.length,has_more:hasMore,source:'native_sticker_search'};}
  finally{emojiNative(0x6569a04,'void',['pointer'])(out);}
 }finally{emojiNative(0x6ea8fe0,'void',['pointer'])(request);}
}
rpc.exports={prepare(expectedTid,parameters){
 if(emojiState.prepared)throw new Error('Sticker query already prepared');
 if(Process.arch!=='arm64'||Process.pointerSize!==8||!Number.isInteger(expectedTid)||expectedTid<=0)throw new Error('Expected ARM64 executor TID');
 if(!parameters||!['list_saved_stickers','search_stickers'].includes(parameters.operation))throw new Error('Expected sticker query operation');
 if(parameters.operation==='search_stickers'&&(typeof parameters.keyword!=='string'||!parameters.keyword||parameters.keyword.includes('\0')))throw new Error('Expected sticker search keyword');
 if(parameters.native_cursor!==undefined&&(!Number.isSafeInteger(parameters.native_cursor)||parameters.native_cursor<0||parameters.native_cursor>0xffffffff))throw new Error('Expected native search cursor');
 if(parameters.offset!==undefined&&(!Number.isSafeInteger(parameters.offset)||parameters.offset<0))throw new Error('Expected nonnegative offset');
 if(parameters.limit!==undefined&&parameters.limit!==null&&(!Number.isSafeInteger(parameters.limit)||parameters.limit<0))throw new Error('Expected nonnegative limit or null');
 emojiKeep.main=Process.getModuleByName('wechat');
 emojiValidate(0x66362d0,[0x3944c409,0x91004000,0x7100013f,0x1a9f17e1]);
 emojiValidate(0x66362e4,[0x3944c409,0x91004000,0x7100013f,0x1a9f17e1]);
 emojiValidate(0x663ac5c,[0x91004000,0x52800021,0x142a9ee8,0x91004000]);
 emojiValidate(0x663ac68,[0x91004000,0x52800021,0x142a9ee5,0xd10103ff]);
 emojiValidate(0x70bc694,[0x17522deb,0xa9bc7bfd,0xf9000bfc,0xa90257f6]);
 emojiValidate(0x603c614,[0xd101c3ff,0xa9057bfd,0xa9064ff4,0x910143fd]);
 emojiValidate(0x6565fdc,[0xd107c3ff,0xa91a7bfd,0xf900dbfc,0xa91c5ff8]);
 emojiValidate(0x65697cc,[0xd105c3ff,0xa9147bfd,0xa91557fc,0xa9164ff4]);
 emojiValidate(0x4fd044c,[0xa9bd7bfd,0xf9000bf5,0xa9024ff4,0x910003fd]);
 emojiValidate(0x6ea8fe0,[0xa9be7bfd,0xf9000bf3,0x910003fd,0xaa0003f3]);
 emojiValidate(0x6569a04,[0xa9bd7bfd,0xa90157f6,0xa9024ff4,0x910003fd]);
 const helper=bridgeKeepalive.module.enumerateSymbols().find(s=>s.name==='rh_post_x8');if(!helper||helper.address.readU32()!==0xaa0403e8||helper.address.add(4).readU32()!==0xd61f00a0)throw new Error('Native sticker sret bridge unavailable');
 emojiKeep.sret=new NativeFunction(helper.address,'void',Array(6).fill('pointer'));emojiKeep.release=emojiNative(0x735c25c,'void',['pointer']);
 emojiKeep.task=new NativeCallback(()=>{if(emojiState.invoked)return;emojiState.invoked=true;emojiState.invocationCount++;
  try{if(Process.getCurrentThreadId()!==expectedTid)throw new Error('Unexpected sticker executor thread');const service=emojiService(),result=parameters.operation==='list_saved_stickers'?emojiSaved(parameters,service):emojiSearchPage(parameters,service);send({kind:'emoji_query_result',result,error:''});emojiState.completionCount++;}
  catch(error){emojiState.errors.push({where:'emoji_query',message:String(error)});}
  finally{for(const shared of emojiKeep.shared.reverse())emojiKeep.release(shared);emojiState.completed=true;emojiState.destroyed=true;}
 },'void',['pointer']);emojiState.prepared=true;return emojiKeep.task.toString();
},status(){return Object.assign({},emojiState);}};
