'use strict';
// Native SNS page requests and the client's own complete SnsDataItem XML writer.
const momentsState={prepared:false,invoked:false,completed:false,destroyed:false,invocationCount:0,completionCount:0,errors:[]};
const momentsKeep={strings:[],shared:[]};
function momentsNative(offset,result,args){return new NativeFunction(momentsKeep.main.base.add(offset),result,args);}
function momentsValidate(offset,words){const p=momentsKeep.main.base.add(offset);words.forEach((word,i)=>{if(p.add(i*4).readU32()!==word)throw new Error('Moments entry mismatch at '+offset.toString(16));});}
function momentsReadString(p){const flag=p.readU8(),n=(flag&1)?p.add(8).readU64().toNumber():flag>>>1;if(!(flag&1)&&n>22)throw new Error('Invalid native moments short string');return n?((flag&1)?p.add(16).readPointer():p.add(1)).readUtf8String(n):'';}
function momentsString(text){const out=Memory.alloc(24),data=Memory.allocUtf8String(text),n=unescape(encodeURIComponent(text)).length;out.writeByteArray(new Uint8Array(24));if(n<=22){out.writeU8(n*2);out.add(1).writeUtf8String(text);}else{out.writeU64(uint64(Math.ceil((n+1)/16)*16).or(1));out.add(8).writeU64(n);out.add(16).writePointer(data);}momentsKeep.strings.push(out,data);return out;}
function momentsSret(offset,out,args=[]){const values=args.slice();while(values.length<4)values.push(ptr(0));momentsKeep.sret(...values,out,momentsKeep.main.base.add(offset));}
function momentsShared(offset,args=[]){const out=Memory.alloc(16);out.writeByteArray(new Uint8Array(16));momentsSret(offset,out,args);momentsKeep.shared.push(out);return out.readPointer();}
function momentsService(){const context=momentsShared(0x5eee0b4);if(context.isNull())throw new Error('No logged-in context');const session=momentsShared(0x602cd40,[context]);if(session.isNull())throw new Error('No logged-in session');const service=momentsShared(0x5ffccb0,[session]);if(service.isNull())throw new Error('No native SNS service');return service;}
function momentsItem(item){
 if(item.isNull())throw new Error('Missing native SNS item');
 const xml=Memory.alloc(24);xml.writeByteArray(new Uint8Array(24));
 momentsSret(0x5fedf04,xml,[item]);
 try{return {moment_id:item.readU64().toString(),author_id:momentsReadString(item.add(0x168)),created_at:item.add(0x184).readU32(),text:momentsReadString(item.add(0x188)),is_private:!!item.add(0x180).readU8(),is_top:!!item.add(0x160).readU8(),native_xml:momentsReadString(xml)};}
 finally{if(xml.readU8()&1)momentsKeep.free(xml.add(16).readPointer());}
}
function momentsCachedPage(service,maxId,contactId){
 // Same local-page getter called by the native timeline controller before its
 // server request (0x5ffae24..0x5ffae38). Native page sizes are 40 and 10.
 const words=momentsNative(0x69fbf48,Array(3).fill('uint64'),['pointer','uint','uint64','pointer','uint'])(service,contactId?10:40,uint64(maxId),momentsString(contactId||''),4);
 const out=Memory.alloc(24);words.forEach((word,i)=>out.add(i*8).writeU64(word));
 const begin=out.readPointer(),end=out.add(8).readPointer(),bytes=end.sub(begin).toInt32();
 if(bytes<0||bytes%16)throw new Error('Invalid native cached SNS item vector');
 const rows=[];try{for(let i=0;i<bytes;i+=16)rows.push(momentsItem(begin.add(i).readPointer()));return rows;}
 finally{for(let i=bytes-16;i>=0;i-=16)momentsKeep.release(begin.add(i));if(!begin.isNull())momentsKeep.free(begin);}
}
function momentsPage(service,maxId,minId,contactId){
 const out=Memory.alloc(48);out.writeByteArray(new Uint8Array(48));
 momentsState.stage='fetch_native_page';
 let continuation=null;
 const observer=contactId?Interceptor.attach(momentsKeep.main.base.add(0x6a0b92c),{onEnter(){if(Process.getCurrentThreadId()===momentsKeep.expectedTid)this.result=this.context.x8;},onLeave(){if(!this.result)return;try{if(this.result.readS32()===0){const response=this.result.add(0x20).readPointer();if(!response.isNull())continuation=response.add(0x58).readU64().toString();}}catch(error){momentsState.errors.push({where:'moments_continue_id',message:String(error)});}}}):null;
 if(observer)Interceptor.flush();
 try{
 if(contactId){const words=momentsNative(0x6a09ae0,Array(6).fill('uint64'),['pointer','uint64','uint64','pointer','uint'])(service,uint64(maxId),uint64(minId),momentsString(contactId),0);words.forEach((word,i)=>out.add(i*8).writeU64(word));}
 else momentsSret(0x6a03da8,out,[service,ptr(uint64(maxId)),ptr(uint64(minId)),ptr(0)]);
 }finally{if(observer){observer.detach();Interceptor.flush();}}
 try{
  const errorType=out.readS32(),errorCode=out.add(4).readS32(),page=out.add(0x20).readPointer();
  const albumState=contactId&&!page.isNull()?page.add(0x50).readU32():null;
  // Album business logic and its UI check ErrorType, and map 0/202/207
  // into normal album state 1 (0x6a0afa0..0x6a0b000, 0x6001ec0).
  // Preserve the native code; do not discard a usable business page.
  if(errorType!==0||(errorCode!==0&&!(contactId&&albumState===1)))return {success:false,native_error_type:errorType,native_error_code:errorCode,native_album_state:albumState,error_message:momentsReadString(out.add(8))};
  if(page.isNull())throw new Error('Native SNS returned no page');
  const begin=page.readPointer(),end=page.add(8).readPointer(),bytes=end.sub(begin).toInt32();
  if(bytes<0||bytes%16)throw new Error('Invalid native SNS item vector');
  momentsState.stage='decode_native_page';const rows=[];
  for(let i=0;i<bytes;i+=16)rows.push(momentsItem(begin.add(i).readPointer()));
  const topBegin=page.add(0x18).readPointer(),topEnd=page.add(0x20).readPointer(),topBytes=topEnd.sub(topBegin).toInt32();
  if(topBytes<0||topBytes%16)throw new Error('Invalid native pinned SNS item vector');
  const topRows=[];for(let i=0;i<topBytes;i+=16)topRows.push(momentsItem(topBegin.add(i).readPointer()));
  return {success:true,moments:rows,top_moments:topRows,native_error_type:errorType,native_error_code:errorCode,native_album_state:albumState,native_not_modified:!!page.add(0x48).readU8(),server_object_count:page.add(0x4c).readU32(),native_continue_id:continuation};
 }finally{momentsKeep.destroyResult(out);}
}
function momentsRead(parameters){
 const service=momentsService(),contactId=parameters.contact_id||null,limit=parameters.limit===undefined?20:parameters.limit;
 let cursor=parameters.cursor;if(typeof cursor==='string')cursor=JSON.parse(cursor);
 const maxId=cursor?cursor.max_id:'0';
 // The native UI uses the final existing item's ID for the next descending
 // request; its first request has ID 0. The second ID is the local-cache lower bound used
 // by the client, and its small-cache path passes 0 (0x5ffb524).
 const page=momentsPage(service,maxId,'0',contactId);
 if(!page.success)return Object.assign(page,{source:'native_sns',pages_fetched:1});
 let cacheReused=false;if(page.native_not_modified&&page.moments.length===0){page.moments=momentsCachedPage(service,maxId,contactId);cacheReused=true;}
 const rows=limit===0||limit===null?page.moments:page.moments.slice(0,limit);
 const lastId=rows.length?rows[rows.length-1].moment_id:(!page.native_not_modified&&page.native_continue_id&&page.native_continue_id!=='0'?page.native_continue_id:maxId);
 // +0x48 means cached first-page MD5 matched, NOT that older pages end.
 // A fresh empty album page ends only when the real server ContinueId is 0.
 // Nonzero ContinueId can cross filtered empty segments, just as the client does.
 const exhausted=!page.native_not_modified&&page.moments.length===0&&(!contactId||page.native_continue_id==='0');
 const stalled=!exhausted&&lastId===maxId;
 const continuationOnly=rows.length===0&&!exhausted&&!stalled;
 return {success:true,moments:rows,top_moments:page.top_moments,returned:rows.length,contact_id:contactId,source:cacheReused?'native_sns_validated_cache':'native_sns',pages_fetched:1,exhausted,has_more:!exhausted,next_cursor:exhausted?null:JSON.stringify({max_id:lastId,contact_id:contactId}),pagination_stalled:stalled,continuation_only:continuationOnly,native_error_type:page.native_error_type,native_error_code:page.native_error_code,native_album_state:page.native_album_state,native_not_modified:page.native_not_modified,native_continue_id:page.native_continue_id,cache_reused:cacheReused,server_object_count:page.server_object_count,native_page_size:page.moments.length};
}
rpc.exports={prepare(expectedTid,parameters){
 if(momentsState.prepared)throw new Error('Moments task already prepared');
 if(Process.arch!=='arm64'||Process.pointerSize!==8||!Number.isInteger(expectedTid)||expectedTid<=0)throw new Error('Expected ARM64 executor TID');
 if(!parameters||!(parameters.limit===undefined||parameters.limit===null||Number.isInteger(parameters.limit)&&parameters.limit>=0))throw new Error('Expected nonnegative moments limit');
 if(parameters.contact_id!=null&&(typeof parameters.contact_id!=='string'||parameters.contact_id.length===0||parameters.contact_id.includes('\0')))throw new Error('Expected contact ID');
 let cursor=parameters.cursor;if(typeof cursor==='string')cursor=JSON.parse(cursor);if(cursor!=null&&(!/^\d+$/.test(cursor.max_id)||uint64(cursor.max_id).toString()!==cursor.max_id))throw new Error('Invalid native moments cursor');if(cursor!=null&&(cursor.contact_id||null)!==(parameters.contact_id||null))throw new Error('Moments cursor belongs to another timeline');
 momentsKeep.main=Process.getModuleByName('wechat');momentsKeep.expectedTid=expectedTid;
 momentsValidate(0x5ffccb0,[0xd101c3ff,0xa9057bfd,0xa9064ff4,0x910143fd]);
 momentsValidate(0x6a03da8,[0xa9ba7bfd,0xa9016ffc,0xa90267fa,0xa9035ff8]);
 momentsValidate(0x6a09ae0,[0xa9ba7bfd,0xa9016ffc,0xa90267fa,0xa9035ff8]);
 momentsValidate(0x5fedf04,[0xa9bb7bfd,0xf9000bfc,0xa9025ff8,0xa90357f6]);
 momentsValidate(0x6a0b92c,[0xfc190fe8,0xa9017bfd,0xa9026ffc,0xa90367fa]);
 momentsValidate(0x69fbf48,[0xd101c3ff,0xa9037bfd,0xf90023f7,0xa90557f6]);
 momentsValidate(0x6a075c8,[0xa9be7bfd,0xa9014ff4,0x910003fd,0xf9401413]);
 const helper=bridgeKeepalive.module.enumerateSymbols().find(symbol=>symbol.name==='rh_post_x8');if(!helper||helper.address.readU32()!==0xaa0403e8||helper.address.add(4).readU32()!==0xd61f00a0)throw new Error('Native moments sret bridge unavailable');
 momentsKeep.sret=new NativeFunction(helper.address,'void',Array(6).fill('pointer'));momentsKeep.release=momentsNative(0x735c25c,'void',['pointer']);momentsKeep.free=momentsNative(0x4499070,'void',['pointer']);momentsKeep.destroyResult=momentsNative(0x6a075c8,'void',['pointer']);
 momentsKeep.task=new NativeCallback(()=>{if(momentsState.invoked)return;momentsState.invoked=true;momentsState.invocationCount++;
  try{if(Process.getCurrentThreadId()!==expectedTid)throw new Error('Unexpected moments executor thread');const result=momentsRead(parameters);send({kind:'moments_read_result',result,error:''});momentsState.completionCount++;}
  catch(error){momentsState.errors.push({where:'moments_read',message:String(error),stage:momentsState.stage});}
  finally{for(const shared of momentsKeep.shared.reverse())momentsKeep.release(shared);momentsState.completed=true;momentsState.destroyed=true;}
 },'void',['pointer']);momentsState.prepared=true;return momentsKeep.task.toString();
},status(){return Object.assign({},momentsState);}};
