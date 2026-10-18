'use strict';

// Native read-query experiment for the researched ARM64 build only.
// The parent verifies executable SHA-256/PID and runs taskAddress through its
// native executor on the appropriate application thread. Loading this file or
// calling prepare() never invokes the adapter. No timeout or unload is scheduled.
const MAX_STRING_BYTES = 64 * 1024;
const ADAPTER_OFFSET = 0x6c4c50c;
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
    if (nativeLength.compare(uint64(MAX_STRING_BYTES)) > 0) {
      throw new Error('Completion string exceeds 64 KiB limit');
    }
    length = nativeLength.toNumber();
    data = address.add(16).readPointer();
    if (length !== 0 && data.isNull()) throw new Error('Null long-string data');
  }
  if (length > MAX_STRING_BYTES) throw new Error('Completion string exceeds limit');
  return length === 0 ? '' : data.readUtf8String(length);
}

function makeFixedInput(text) {
  // Bounded query JSON is ASCII-escaped before native string allocation.
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
      throw new Error('Contact adapter prologue mismatch');
    }
  }
  if (queryKeepalive.mainBase !== undefined &&
      !queryKeepalive.mainBase.equals(main.base)) {
    throw new Error('Bound main module base changed');
  }
  queryKeepalive.mainBase = main.base;
  return entry;
}

rpc.exports = {
  prepare(expectedTid, parameters) {
    if (!Number.isInteger(expectedTid) || expectedTid <= 0) throw new Error("Expected verified executor TID");
    if (!parameters || !Array.isArray(parameters.keywords) ||
        parameters.keywords.length < 1 || parameters.keywords.length > 8 ||
        parameters.keywords.some(x => typeof x !== 'string' || !x.trim() || x.length > 128 || x.includes('\0')) ||
        !Number.isInteger(parameters.limit) || parameters.limit < 1 || parameters.limit > 50 ||
        (parameters.filter_type !== 1 && parameters.filter_type !== 2) ||
        parameters.only_authorized !== false || parameters.sort_by_time !== false) {
      throw new Error('Invalid bounded contact query');
    }
    const entry = validateAdapter();
    if (queryState.prepared) return queryKeepalive.task.toString();

    FIXED_QUERY = parameters;
    const json = JSON.stringify(parameters).replace(/[\u007f-\uffff]/g,
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
          kind: 'contact_query_result',
          query: FIXED_QUERY,
          result: result,
          error: errorText
        });
      } catch (e) {
        recordQueryError('completion', e);
        send({kind: 'contact_query_result', result: null,
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
        send({kind: 'contact_query_error', errors: queryState.errors.slice()});
        return;
      }
      queryState.invoked = true;
      queryState.invocationCount++;
      try {
        validateAdapter();
        queryKeepalive.adapter(ptr(0), queryKeepalive.input,
          queryKeepalive.context, queryKeepalive.wrapper);
      } catch (e) {
        recordQueryError('adapter', e);
        send({kind: 'contact_query_error', errors: queryState.errors.slice()});
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
