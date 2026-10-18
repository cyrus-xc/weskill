'use strict';

// Native message-list adapter with caller-selected count and XML fields.
// The parent verifies executable SHA-256/PID and runs taskAddress through its
// native executor on the appropriate application thread. Loading this file or
// calling prepare() never invokes the adapter. No timeout or unload is scheduled.
const ADAPTER_OFFSET = 0x6c4f864;
let FIXED_QUERY;
const queryState = {
  prepared: false,
  invoked: false,
  completed: false,
  destroyed: false,
  invocationCount: 0,
  completionCount: 0,
  errors: []
};
// Retain buffers, function wrappers and callbacks for the entire script lifetime.
// In particular, an asynchronous callback must never outlive a NativeCallback.
const queryKeepalive = {};

function recordQueryError(where, error) {
  queryState.errors.push({where: where, message: String(error)});
}

function readCppString(address) {
  if (address.isNull()) throw new Error('Null std::string pointer');
  const flag = address.readU8();
  let data;
  let length;
  if ((flag & 1) === 0) {
    length = flag >>> 1;
    if (length > 22) throw new Error('Invalid libc++ short-string length');
    data = address.add(1);
  } else {
    const nativeLength = address.add(8).readU64();
    length = nativeLength.toNumber();
    data = address.add(16).readPointer();
    if (length !== 0 && data.isNull()) throw new Error('Null long-string data');
  }
  return length === 0 ? '' : data.readUtf8String(length);
}

function makeFixedInput(text) {
  // Query JSON is ASCII-escaped before native string allocation.
  if (!/^[\x20-\x7e]*$/.test(text)) throw new Error('Expected ASCII-escaped JSON');
  const object = Memory.alloc(24);
  object.writeByteArray(new Uint8Array(24));
  if (text.length <= 22) {
    object.writeU8(text.length << 1);
    object.add(1).writeUtf8String(text);
  } else {
    const allocationSize = Math.ceil((text.length + 1) / 16) * 16;
    const storage = Memory.alloc(allocationSize);
    storage.writeUtf8String(text);
    object.writeU64(uint64(allocationSize).or(1));
    object.add(8).writeU64(text.length);
    object.add(16).writePointer(storage);
    queryKeepalive.inputStorage = storage;
  }
  return object;
}

function validateAdapter() {
  if (Process.arch !== 'arm64' || Process.pointerSize !== 8) {
    throw new Error('Expected 64-bit ARM64 process');
  }
  const main = Process.getModuleByName('wechat');
  if (main.size <= ADAPTER_OFFSET + 16) throw new Error('Unexpected main module size');
  const entry = main.base.add(ADAPTER_OFFSET);
  const expected = [0xd10343ff, 0xa9097bfd, 0xf90053f7, 0xa90b57f6];
  for (let i = 0; i < expected.length; i++) {
    if (entry.add(i * 4).readU32() !== expected[i]) {
      throw new Error('Message list adapter prologue mismatch');
    }
  }
  if (queryKeepalive.mainBase !== undefined &&
      !queryKeepalive.mainBase.equals(main.base)) {
    throw new Error('Bound main module base changed');
  }
  queryKeepalive.mainBase = main.base;
  return entry;
}

function withRequestedLimit(expectedTid, requested, invoke) {
  if (requested <= 200) return invoke();
  const entry = queryKeepalive.mainBase.add(0x6c9b654);
  const expected = [0xfc190fe8, 0xa9017bfd, 0xa9026ffc, 0xa90367fa];
  expected.forEach((word, i) => {
    if (entry.add(i * 4).readU32() !== word) throw new Error('Query business prologue mismatch');
  });
  const hook = Interceptor.attach(entry, {
    onEnter(args) {
      if (Process.getCurrentThreadId() === expectedTid) args[1].add(72).writeS32(requested);
    }
  });
  try {
    Interceptor.flush();
    return invoke();
  } finally {
    hook.detach();
    Interceptor.flush();
  }
}

rpc.exports = {
  prepare(expectedTid, parameters) {
    if (!Number.isInteger(expectedTid) || expectedTid <= 0) throw new Error("Expected verified executor TID");
    if (!parameters || !Array.isArray(parameters.chat_ids) ||
        parameters.chat_ids.length < 1 ||
        parameters.chat_ids.some(x => typeof x !== 'string' ||
          !x.trim() || x.includes('\0')) ||
        !(Number.isInteger(parameters.limit) && parameters.limit > 0) ||
        typeof parameters.include_xml !== 'boolean') {
      throw new Error('Invalid message list query');
    }
    const entry = validateAdapter();
    if (queryState.prepared) return queryKeepalive.task.toString();

    FIXED_QUERY = {chat_ids: parameters.chat_ids.slice(), limit: parameters.limit, include_xml: parameters.include_xml};
    if (parameters.end_time !== undefined) FIXED_QUERY.end_time = parameters.end_time;
    const json = JSON.stringify({...FIXED_QUERY, limit: Math.min(parameters.limit || 1, 200)}).replace(/[\u007f-\uffff]/g,
      ch => '\\u' + ch.charCodeAt(0).toString(16).padStart(4, '0'));
    queryKeepalive.input = makeFixedInput(json);
    queryKeepalive.context = Memory.alloc(24);
    queryKeepalive.context.writeByteArray(new Uint8Array(24));
    queryKeepalive.callbackObject = Memory.alloc(32);
    queryKeepalive.callbackObject.writeByteArray(new Uint8Array(32));
    queryKeepalive.wrapper = Memory.alloc(8);

    queryKeepalive.invoke = new NativeCallback((self, output, error) => {
      queryState.completionCount++;
      try {
        if (!self.equals(queryKeepalive.callbackObject)) {
          throw new Error('Unexpected completion self pointer');
        }
        if (queryState.completionCount !== 1) throw new Error('Duplicate completion');
        // Native strings are borrowed temporaries: copy during this callback.
        const outputText = readCppString(output);
        const errorText = readCppString(error);
        const result = outputText.length === 0 ? null : JSON.parse(outputText);
        send({
          kind: 'message_list_result',
          query: FIXED_QUERY,
          result: result,
          // Preserve numeric svr_id beyond JavaScript safe-integer precision.
          raw_json: outputText,
          error: errorText
        });
      } catch (e) {
        recordQueryError('completion', e);
        send({kind: 'message_list_result', result: null,
          error: 'Completion could not be decoded', errors: queryState.errors.slice()});
      } finally {
        queryState.completed = true;
      }
    }, 'void', ['pointer', 'pointer', 'pointer']);

    queryKeepalive.destroy = new NativeCallback(self => {
      try {
        if (!self.equals(queryKeepalive.callbackObject)) {
          throw new Error('Unexpected destroy self pointer');
        }
        if (queryState.destroyed) throw new Error('Duplicate destroy');
        queryState.destroyed = true;
      } catch (e) {
        recordQueryError('destroy', e);
      }
      // Memory.alloc storage belongs to Frida. Never pass it to operator delete.
    }, 'void', ['pointer']);
    queryKeepalive.query = new NativeCallback((self, kind) => kind !== 0 ? 1 : 0,
      'int', ['pointer', 'int']);

    const object = queryKeepalive.callbackObject;
    object.writeU32(1); // Native release helper decrements a 32-bit atomic count.
    object.add(8).writePointer(queryKeepalive.invoke);
    object.add(16).writePointer(queryKeepalive.destroy);
    object.add(24).writePointer(queryKeepalive.query);
    queryKeepalive.wrapper.writePointer(object);
    queryKeepalive.adapter = new NativeFunction(entry, 'void',
      ['pointer', 'pointer', 'pointer', 'pointer']);

    queryKeepalive.task = new NativeCallback(userdata => {
      if (queryState.invoked) {
        recordQueryError('task', 'One-shot task invoked more than once');
        return;
      }
      if (Process.getCurrentThreadId() !== expectedTid) {
        recordQueryError('task', 'Unexpected executor thread; query refused');
        send({kind: 'message_list_error', errors: queryState.errors.slice()});
        return;
      }
      queryState.invoked = true;
      queryState.invocationCount++;
      try {
        validateAdapter();
        withRequestedLimit(expectedTid, parameters.limit, () =>
          queryKeepalive.adapter(ptr(0), queryKeepalive.input,
            queryKeepalive.context, queryKeepalive.wrapper));
      } catch (e) {
        recordQueryError('adapter', e);
        send({kind: 'message_list_error', errors: queryState.errors.slice()});
      }
    }, 'void', ['pointer']);
    queryState.prepared = true;
    return queryKeepalive.task.toString();
  },

  status() {
    return {
      prepared: queryState.prepared,
      invoked: queryState.invoked,
      completed: queryState.completed,
      destroyed: queryState.destroyed,
      invocationCount: queryState.invocationCount,
      completionCount: queryState.completionCount,
      errors: queryState.errors.slice()
    };
  }
};
