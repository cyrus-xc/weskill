'use strict';
// Read the contact service's local record on the established application executor.
// The outer backend binds this script to the researched executable hash.
const profileState={prepared:false,invoked:false,completed:false,destroyed:false,
  invocationCount:0,completionCount:0,errors:[]};
const profileKeep={strings:[],shared:[]};
function profileReadString(p) {
  if(p.isNull())throw new Error('Missing native profile string');
  const flag=p.readU8();
  const n=(flag&1)?p.add(8).readU64().toNumber():flag>>>1;
  if(!(flag&1)&&n>22)throw new Error('Invalid native profile short string');
  const data=(flag&1)?p.add(16).readPointer():p.add(1);
  return n===0?'':data.readUtf8String(n);
}
function profileString(value) {
  const p=Memory.alloc(24),data=Memory.allocUtf8String(value);
  const n=unescape(encodeURIComponent(value)).length;
  p.writeByteArray(new Uint8Array(24));
  if(n<=22){p.writeU8(n*2);p.add(1).writeUtf8String(value);}
  else {p.writeU64(uint64(n+1).or(1));p.add(8).writeU64(n);p.add(16).writePointer(data);}
  profileKeep.strings.push(p,data);return p;
}
function profileValidate(offset,expected) {
  const entry=profileKeep.main.base.add(offset);
  for(let i=0;i<expected.length;i++)if(entry.add(i*4).readU32()!==expected[i])
    throw new Error('Profile entry mismatch at '+offset.toString(16));
  return entry;
}
function profileShared(offset,args=[]) {
  const out=Memory.alloc(16);out.writeByteArray(new Uint8Array(16));
  const values=args.slice();while(values.length<4)values.push(ptr(0));
  profileKeep.sret(...values,out,profileKeep.main.base.add(offset));
  profileKeep.shared.push(out);return out.readPointer();
}
function profilePhoneNumbers(record) {
  const list=record.add(0x1d0).readPointer();
  if(list.isNull())return [];
  const count=list.add(0x10).readS32(),items=list.add(8).readPointer();
  if(count<0||(count>0&&items.isNull()))throw new Error('Invalid native phone-number list');
  const numbers=[];
  for(let i=0;i<count;i++) {
    const item=items.add(i*8).readPointer();
    if(item.isNull())throw new Error('Missing native phone-number item');
    numbers.push(profileReadString(item.add(8).readPointer()));
  }
  return numbers;
}
// ContactExtData label-ID CSV is resolved against the local label service cache.
function profileLabels(record,session) {
  const raw=profileReadString(record.add(0x238).readPointer());
  const ids=raw.split(',').filter(id=>id.length>0);
  if(ids.length===0)return {label_ids:[],labels:[]};
  if(profileKeep.labelService===undefined)
    profileKeep.labelService=profileShared(0x603db0c,[session]);
  const service=profileKeep.labelService;
  const labels=ids.map(id=>{
    const label={label_id:id};
    if(!service.isNull()) {
      const map=service.add(0x38);
      const node=profileKeep.findLabel(map,profileString(id));
      if(!node.equals(map.add(8)))label.label_name=profileReadString(node.add(0x40));
    }
    return label;
  });
  return {label_ids:ids,labels:labels};
}
// These labels are proven by the client's add-source converter and Chinese table.
const profileAddSources={1:'通过搜索QQ号添加',3:'通过搜索微信号添加',6:'朋友验证',
  10:'通过手机通讯录添加',14:'通过群聊添加',15:'通过搜索手机号添加',
  17:'通过名片分享添加',18:'通过附近的人添加',30:'通过扫一扫添加',31:'来自Facebook联系人'};
function profileContacts(ids) {
  const context=profileShared(0x5eee0b4);
  if(context.isNull())throw new Error('No logged-in context');
  const session=profileShared(0x602cd40,[context]);
  if(session.isNull())throw new Error('No logged-in session');
  const service=profileShared(0x5faa590,[session]);
  if(service.isNull())throw new Error('No native contact service');
  const contacts=[];
  for(const id of ids) {
    const record=profileShared(0x7547d4c,[service,profileString(id)]);
    if(record.isNull()) {contacts.push({contact_id:id,username:id,found:false,
      source:'local_native_cache'});continue;}
    const username=profileReadString(record.add(8));
    if(username!==id)throw new Error('Native contact profile ID mismatch');
    const profile={contact_id:id,username:username,found:true,
      source:'local_native_cache',local_type:record.add(4).readU32(),
      alias:profileReadString(record.add(0x20)),
      nickname:profileReadString(record.add(0xa8)),
      remark:profileReadString(record.add(0x60)),
      description:profileReadString(record.add(0x140)),
      remark_full_pinyin:profileReadString(record.add(0x78)),
      remark_pinyin_initial:profileReadString(record.add(0x90)),
      nickname_pinyin_initial:profileReadString(record.add(0xc0)),
      nickname_full_pinyin:profileReadString(record.add(0xd8)),
      avatar_url:profileReadString(record.add(0xf0))||profileReadString(record.add(0x108)),
      big_head_url:profileReadString(record.add(0xf0)),
      small_head_url:profileReadString(record.add(0x108)),
      head_img_md5:profileReadString(record.add(0x120)),
      native_contact_flag:record.add(0x54).readU32(),
      native_delete_flag:record.add(0x50).readU32(),
      verify_flag:record.add(0x58).readU32()};
    // ContactExtData has a different schema for enterprise/local types 5,6,7.
    // Ordinary contact fields below follow the client's account-info converter.
    if(![5,6,7].includes(profile.local_type)) {
      profile.sex=profileKeep.sex(record);
      profile.signature=profileReadString(record.add(0x198).readPointer());
      profile.country=profileReadString(record.add(0x1a0).readPointer());
      profile.province=profileReadString(record.add(0x1a8).readPointer());
      profile.city=profileReadString(record.add(0x1b0).readPointer());
      profile.phone_numbers=profilePhoneNumbers(record);
      Object.assign(profile,profileLabels(record,session));
      profile.add_source_scene=record.add(0x1b8).readU32();
      if(Object.prototype.hasOwnProperty.call(profileAddSources,profile.add_source_scene))
        profile.add_source=profileAddSources[profile.add_source_scene];
    } else {
      profile.sex=profileKeep.sex(record);
      profile.extended_profile_available=false;
    }
    contacts.push(profile);
  }
  return {success:true,contacts:contacts,source:'local_native_cache',remote_refreshed:false};
}
rpc.exports={
  prepare(expectedTid,parameters) {
    if(profileState.prepared)throw new Error('Profile task already prepared');
    if(Process.arch!=='arm64'||Process.pointerSize!==8||
      !Number.isInteger(expectedTid)||expectedTid<=0)throw new Error('Expected ARM64 executor TID');
    if(!parameters||!Array.isArray(parameters.contact_ids)||parameters.contact_ids.length===0||
      parameters.contact_ids.some(id=>typeof id!=='string'||id.length===0||id.includes('\0')))
      throw new Error('Expected contact IDs');
    profileKeep.main=Process.getModuleByName('wechat');
    profileValidate(0x5eee0b4,[0xd100c3ff,0xa9017bfd,0xf90013f3,0x910043fd]);
    profileValidate(0x602cd40,[0xa942a40a,0xa900250a,0xb40000c9,0x91002128]);
    profileValidate(0x5faa590,[0xd101c3ff,0xa9057bfd,0xa9064ff4,0x910143fd]);
    profileValidate(0x7547d4c,[0xa9bb7bfd,0xf9000bfc,0xa9025ff8,0xa90357f6]);
    profileValidate(0x603db0c,[0xd101c3ff,0xa9057bfd,0xa9064ff4,0x910143fd]);
    const findLabel=profileValidate(0x75fce00,[0xa9bc7bfd,0xa9015ff8,0xa90257f6,0xa9034ff4]);
    const release=profileValidate(0x735c25c,[0xa9be7bfd,0xf9000bf3,0x910003fd,0xf9400413]);
    const sex=profileValidate(0x5f4a844,[0xb9400408,0x9106400a,0x910b400b,0x51001509]);
    const helper=bridgeKeepalive.module.enumerateSymbols().find(s=>s.name==='rh_post_x8');
    if(!helper||helper.address.readU32()!==0xaa0403e8||helper.address.add(4).readU32()!==0xd61f00a0)
      throw new Error('Native profile sret bridge unavailable');
    profileKeep.sret=new NativeFunction(helper.address,'void',Array(6).fill('pointer'));
    profileKeep.release=new NativeFunction(release,'void',['pointer']);
    profileKeep.findLabel=new NativeFunction(findLabel,'pointer',['pointer','pointer']);
    profileKeep.sex=new NativeFunction(sex,'int',['pointer']);
    profileKeep.task=new NativeCallback(()=>{
      if(profileState.invoked)return;
      profileState.invoked=true;profileState.invocationCount++;
      try {
        if(Process.getCurrentThreadId()!==expectedTid)throw new Error('Unexpected profile executor thread');
        const result=profileContacts(parameters.contact_ids);
        send({kind:'friend_profile_result',result:result,error:''});
        profileState.completionCount++;
      } catch(error){profileState.errors.push({where:'friend_profile',message:String(error)});}
      finally {
        for(const shared of profileKeep.shared.reverse())profileKeep.release(shared);
        profileState.completed=true;profileState.destroyed=true;
      }
    },'void',['pointer']);
    profileState.prepared=true;return profileKeep.task.toString();
  },
  status(){return Object.assign({},profileState);}
};
