'use strict';

// One-shot native media-send preparation for the researched ARM64 build only.
// The parent verifies executable SHA-256/PID and runs taskAddress through its
// native executor on the appropriate application thread. Loading this file or
// calling prepare() never invokes the adapter. No timeout, retry or unload is
// scheduled. Parent submits once and retains callbacks through client exit.
const ADAPTER_OFFSET = 0x6c52988;
const mediaSendState = {
  prepared: false,
  attempted: false,
  invoked: false,
  completed: false,
  destroyed: false,
  invocationCount: 0,
  completionCount: 0,
  errors: []
};
// Retain buffers, function wrappers and callbacks for the entire script lifetime.
// In particular, an asynchronous callback must never outlive a NativeCallback.
const mediaSendKeepalive = {};

function recordSendError(where, error) {
  mediaSendState.errors.push({where: where, message: String(error)});
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
  // prepare() creates ASCII-escaped JSON; no native API is called here.
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
    mediaSendKeepalive.inputStorage = storage;
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
      throw new Error('Media-send adapter prologue mismatch');
    }
  }
  if (mediaSendKeepalive.mainBase !== undefined &&
      !mediaSendKeepalive.mainBase.equals(main.base)) {
    throw new Error('Bound main module base changed');
  }
  mediaSendKeepalive.mainBase = main.base;
  return entry;
}

rpc.exports = {
  prepare(expectedTid, parameters) {
    if (!Number.isInteger(expectedTid) || expectedTid <= 0) throw new Error('Expected executor TID');
    const entry = validateAdapter();
    if (!parameters || typeof parameters.chat_id !== 'string' || !parameters.chat_id.trim() ||
        !Number.isInteger(parameters.message_type) || typeof parameters.content_xml !== 'string' ||
        !parameters.content_xml) throw new Error('Invalid media send parameters');
    const json = JSON.stringify(parameters).replace(/[\u007f-\uffff]/g,
      character => '\\u' + character.charCodeAt(0).toString(16).padStart(4, '0'));
    if (mediaSendState.prepared) {
      if (mediaSendKeepalive.expectedTid !== expectedTid || mediaSendKeepalive.json !== json) {
        throw new Error('One-shot media parameters already bound');
      }
      return mediaSendKeepalive.task.toString();
    }
    mediaSendKeepalive.expectedTid = expectedTid;
    mediaSendKeepalive.recipient = parameters.chat_id;
    mediaSendKeepalive.json = json;
    mediaSendKeepalive.input = makeFixedInput(json);
    mediaSendKeepalive.context = Memory.alloc(24);
    mediaSendKeepalive.context.writeByteArray(new Uint8Array(24));
    mediaSendKeepalive.callbackObject = Memory.alloc(32);
    mediaSendKeepalive.callbackObject.writeByteArray(new Uint8Array(32));
    mediaSendKeepalive.wrapper = Memory.alloc(8);

    mediaSendKeepalive.invoke = new NativeCallback((self, output, error) => {
      mediaSendState.completionCount++;
      try {
        if (!self.equals(mediaSendKeepalive.callbackObject)) {
          throw new Error('Unexpected completion self pointer');
        }
        if (mediaSendState.completionCount !== 1) throw new Error('Duplicate completion');
        // Native strings are borrowed temporaries: copy during this callback.
        const outputText = readCppString(output);
        const errorText = readCppString(error);
        const result = outputText.length === 0 ? null : JSON.parse(outputText);
        send({
          kind: 'media_send_result',
          recipient: mediaSendKeepalive.recipient,
          result: result,
          raw_json: outputText,
          deliveryConfirmed: false,
          callbackTid: Process.getCurrentThreadId(),
          error: errorText
        });
      } catch (e) {
        recordSendError('completion', e);
        send({kind: 'media_send_result', result: null, deliveryConfirmed: false,
          error: 'Completion could not be decoded', errors: mediaSendState.errors.slice()});
      } finally {
        mediaSendState.completed = true;
      }
    }, 'void', ['pointer', 'pointer', 'pointer']);

    mediaSendKeepalive.destroy = new NativeCallback(self => {
      try {
        if (!self.equals(mediaSendKeepalive.callbackObject)) {
          throw new Error('Unexpected destroy self pointer');
        }
        if (mediaSendState.destroyed) throw new Error('Duplicate destroy');
        mediaSendState.destroyed = true;
      } catch (e) {
        recordSendError('destroy', e);
      }
      // Memory.alloc storage belongs to Frida. Never pass it to operator delete.
    }, 'void', ['pointer']);
    mediaSendKeepalive.query = new NativeCallback((self, kind) => kind !== 0 ? 1 : 0,
      'int', ['pointer', 'int']);

    const object = mediaSendKeepalive.callbackObject;
    object.writeU32(1); // Native release helper decrements a 32-bit atomic count.
    object.add(8).writePointer(mediaSendKeepalive.invoke);
    object.add(16).writePointer(mediaSendKeepalive.destroy);
    object.add(24).writePointer(mediaSendKeepalive.query);
    mediaSendKeepalive.wrapper.writePointer(object);
    mediaSendKeepalive.adapter = new NativeFunction(entry, 'void',
      ['pointer', 'pointer', 'pointer', 'pointer']);

    mediaSendKeepalive.task = new NativeCallback(userdata => {
      if (mediaSendState.attempted) {
        recordSendError('task', 'One-shot task invoked more than once; send refused');
        return;
      }
      // Mark before any native call. No retry is permitted even after an error
      // or a wrong-thread refusal; partial native execution cannot be ruled out.
      mediaSendState.attempted = true;
      if (Process.getCurrentThreadId() !== expectedTid) {
        recordSendError('task', 'Unexpected executor thread; send refused');
        send({kind: 'media_send_error', errors: mediaSendState.errors.slice()});
        return;
      }
      mediaSendState.invoked = true;
      mediaSendState.invocationCount++;
      try {
        validateAdapter();
        mediaSendKeepalive.adapter(ptr(0), mediaSendKeepalive.input,
          mediaSendKeepalive.context, mediaSendKeepalive.wrapper);
      } catch (e) {
        recordSendError('adapter', e);
        send({kind: 'media_send_error', errors: mediaSendState.errors.slice()});
      }
    }, 'void', ['pointer']);
    mediaSendState.prepared = true;
    return mediaSendKeepalive.task.toString();
  },

  status() {
    return {
      prepared: mediaSendState.prepared,
      attempted: mediaSendState.attempted,
      recipient: mediaSendKeepalive.recipient || null,

      invoked: mediaSendState.invoked,
      completed: mediaSendState.completed,
      destroyed: mediaSendState.destroyed,
      invocationCount: mediaSendState.invocationCount,
      completionCount: mediaSendState.completionCount,
      errors: mediaSendState.errors.slice()
    };
  }
};
