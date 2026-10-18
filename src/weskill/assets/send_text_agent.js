'use strict';

// One-shot native text-send preparation for the researched ARM64 build only.
// The parent verifies executable SHA-256/PID and runs taskAddress through its
// native executor on the appropriate application thread. Loading this file or
// calling prepare() never invokes the adapter. No timeout, retry or unload is
// scheduled. Parent must submit at most once and await callback destruction.
const ADAPTER_OFFSET = 0x6c53230;
const textSendState = {
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
const textSendKeepalive = {};

function recordSendError(where, error) {
  textSendState.errors.push({where: where, message: String(error)});
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
    textSendKeepalive.inputStorage = storage;
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
      throw new Error('Text-send adapter prologue mismatch');
    }
  }
  if (textSendKeepalive.mainBase !== undefined &&
      !textSendKeepalive.mainBase.equals(main.base)) {
    throw new Error('Bound main module base changed');
  }
  textSendKeepalive.mainBase = main.base;
  return entry;
}

rpc.exports = {
  prepare(expectedTid, recipient, text) {
    if (!Number.isInteger(expectedTid) || expectedTid <= 0) throw new Error("Expected verified executor TID");
    const entry = validateAdapter();
    if (typeof recipient !== 'string' || !recipient.trim() || recipient.includes('\0')) {
      throw new Error('Expected one verified contact or group id');
    }
    if (typeof text !== 'string' || text.trim().length === 0 ||
        text.indexOf('\0') !== -1) {
      throw new Error('Expected nonempty text without NUL');
    }
    // Reject lone surrogates rather than silently changing the authorized text.
    for (let i = 0; i < text.length; i++) {
      const code = text.charCodeAt(i);
      if (code >= 0xd800 && code <= 0xdbff) {
        const next = text.charCodeAt(++i);
        if (!(next >= 0xdc00 && next <= 0xdfff)) throw new Error('Unpaired text surrogate');
      } else if (code >= 0xdc00 && code <= 0xdfff) {
        throw new Error('Unpaired text surrogate');
      }
    }
    if (textSendState.prepared) {
      if (textSendKeepalive.expectedTid !== expectedTid ||
          textSendKeepalive.recipient !== recipient || textSendKeepalive.text !== text) {
        throw new Error('One-shot recipient/text/TID already bound');
      }
      return textSendKeepalive.task.toString();
    }
    textSendKeepalive.expectedTid = expectedTid;
    textSendKeepalive.recipient = recipient;
    textSendKeepalive.text = text;

    // ASCII JSON escapes preserve exact Unicode while making native byte length
    // equal to JS string length. This function only allocates data, never sends.
    const json = JSON.stringify({chat_id: recipient, content: text}).replace(
      /[\u007f-\uffff]/g, character => '\\u' + character.charCodeAt(0).toString(16).padStart(4, '0'));
    textSendKeepalive.input = makeFixedInput(json);
    textSendKeepalive.context = Memory.alloc(24);
    textSendKeepalive.context.writeByteArray(new Uint8Array(24));
    textSendKeepalive.callbackObject = Memory.alloc(32);
    textSendKeepalive.callbackObject.writeByteArray(new Uint8Array(32));
    textSendKeepalive.wrapper = Memory.alloc(8);

    textSendKeepalive.invoke = new NativeCallback((self, output, error) => {
      textSendState.completionCount++;
      try {
        if (!self.equals(textSendKeepalive.callbackObject)) {
          throw new Error('Unexpected completion self pointer');
        }
        if (textSendState.completionCount !== 1) throw new Error('Duplicate completion');
        // Native strings are borrowed temporaries: copy during this callback.
        const outputText = readCppString(output);
        const errorText = readCppString(error);
        const result = outputText.length === 0 ? null : JSON.parse(outputText);
        send({
          kind: 'text_send_result',
          recipient: textSendKeepalive.recipient,
          result: result,
          raw_json: outputText,
          deliveryConfirmed: false,
          callbackTid: Process.getCurrentThreadId(),
          error: errorText
        });
      } catch (e) {
        recordSendError('completion', e);
        send({kind: 'text_send_result', result: null, deliveryConfirmed: false,
          error: 'Completion could not be decoded', errors: textSendState.errors.slice()});
      } finally {
        textSendState.completed = true;
      }
    }, 'void', ['pointer', 'pointer', 'pointer']);

    textSendKeepalive.destroy = new NativeCallback(self => {
      try {
        if (!self.equals(textSendKeepalive.callbackObject)) {
          throw new Error('Unexpected destroy self pointer');
        }
        if (textSendState.destroyed) throw new Error('Duplicate destroy');
        textSendState.destroyed = true;
      } catch (e) {
        recordSendError('destroy', e);
      }
      // Memory.alloc storage belongs to Frida. Never pass it to operator delete.
    }, 'void', ['pointer']);
    textSendKeepalive.query = new NativeCallback((self, kind) => kind !== 0 ? 1 : 0,
      'int', ['pointer', 'int']);

    const object = textSendKeepalive.callbackObject;
    object.writeU32(1); // Native release helper decrements a 32-bit atomic count.
    object.add(8).writePointer(textSendKeepalive.invoke);
    object.add(16).writePointer(textSendKeepalive.destroy);
    object.add(24).writePointer(textSendKeepalive.query);
    textSendKeepalive.wrapper.writePointer(object);
    textSendKeepalive.adapter = new NativeFunction(entry, 'void',
      ['pointer', 'pointer', 'pointer', 'pointer']);

    textSendKeepalive.task = new NativeCallback(userdata => {
      if (textSendState.attempted) {
        recordSendError('task', 'One-shot task invoked more than once; send refused');
        return;
      }
      // Mark before any native call. No retry is permitted even after an error
      // or a wrong-thread refusal; partial native execution cannot be ruled out.
      textSendState.attempted = true;
      if (Process.getCurrentThreadId() !== expectedTid) {
        recordSendError('task', 'Unexpected executor thread; send refused');
        send({kind: 'text_send_error', errors: textSendState.errors.slice()});
        return;
      }
      textSendState.invoked = true;
      textSendState.invocationCount++;
      try {
        validateAdapter();
        textSendKeepalive.adapter(ptr(0), textSendKeepalive.input,
          textSendKeepalive.context, textSendKeepalive.wrapper);
      } catch (e) {
        recordSendError('adapter', e);
        send({kind: 'text_send_error', errors: textSendState.errors.slice()});
      }
    }, 'void', ['pointer']);
    textSendState.prepared = true;
    return textSendKeepalive.task.toString();
  },

  status() {
    return {
      prepared: textSendState.prepared,
      attempted: textSendState.attempted,
      recipient: textSendKeepalive.recipient || null,
      textCodeUnits: textSendKeepalive.text === undefined ? null : textSendKeepalive.text.length,
      invoked: textSendState.invoked,
      completed: textSendState.completed,
      destroyed: textSendState.destroyed,
      invocationCount: textSendState.invocationCount,
      completionCount: textSendState.completionCount,
      errors: textSendState.errors.slice()
    };
  }
};
