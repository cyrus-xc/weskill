'use strict';

// One-shot native moments-publish preparation for the researched ARM64 build only.
// The parent verifies executable SHA-256/PID and runs taskAddress through its
// native executor on the appropriate application thread. Loading this file or
// calling prepare() never invokes the adapter. No timeout, retry or unload is
// scheduled. Parent must submit at most once and await callback destruction.
const ADAPTER_OFFSET = 0x6c53a18;
const momentsPublishState = {
  prepared: false,
  attempted: false,
  invoked: false,
  completed: false,
  destroyed: false,
  invocationCount: 0,
  completionCount: 0,
  mediaModelTransfers: 0,
  errors: []
};
// Retain buffers, function wrappers and callbacks for the entire script lifetime.
// In particular, an asynchronous callback must never outlive a NativeCallback.
const momentsPublishKeepalive = {};

function recordSendError(where, error) {
  momentsPublishState.errors.push({where: where, message: String(error)});
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
    momentsPublishKeepalive.inputStorage = storage;
    if (!momentsPublishKeepalive.storage) momentsPublishKeepalive.storage = [];
    momentsPublishKeepalive.storage.push(storage);
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
      throw new Error('Moments publish adapter prologue mismatch');
    }
  }
  if (momentsPublishKeepalive.mainBase !== undefined &&
      !momentsPublishKeepalive.mainBase.equals(main.base)) {
    throw new Error('Bound main module base changed');
  }
  momentsPublishKeepalive.mainBase = main.base;
  return entry;
}

function momentsPublishValidateEntry(offset, expected) {
  const address = momentsPublishKeepalive.mainBase.add(offset);
  expected.forEach((word, index) => {
    if (address.add(index * 4).readU32() !== word) throw new Error('Moments native entry mismatch');
  });
  return address;
}
function momentsPublishNative(offset, result, args) {
  return new NativeFunction(momentsPublishKeepalive.mainBase.add(offset), result, args);
}
function momentsPublishXml(text) {
  return Array.from(text).map(c => {
    if (c === '&') return '&amp;';
    if (c === '<') return '&lt;';
    if (c === '>') return '&gt;';
    const n = c.codePointAt(0);
    return n >= 127 ? '&#x' + n.toString(16) + ';' : c;
  }).join('');
}
function momentsPublishPrepareImages(parameters) {
  const images = parameters.images || [];
  if (images.length === 0) return null;
  const controls = momentsPublishKeepalive;
  const control = momentsPublishNative(0x9fa44e8, 'pointer', ['uint64'])(0x270);
  if (control.isNull()) throw new Error('Cannot allocate Moments model');
  control.writeByteArray(new Uint8Array(0x270));
  // Same shared_ptr control and ctor used by native SnsPublishViewModel and
  // create_moments. Only native-new storage is owned by this control block.
  control.writePointer(controls.mainBase.add(0xa44a3a0).readPointer().add(0x10));
  const model = control.add(0x18);
  momentsPublishNative(0x601780c, 'void', ['pointer', 'int'])(model, 9);
  const shared = Memory.alloc(16);
  shared.writePointer(model);
  shared.add(8).writePointer(control);
  controls.imageModel = shared;
  const media = images.map(image => '<upload_media><type>2</type><client_id>' +
    momentsPublishXml(image.client_id) + '</client_id><local_src_url>' +
    momentsPublishXml(image.source_path) + '</local_src_url><local_data_url>' +
    momentsPublishXml(image.data_path) + '</local_data_url><local_thumb_url>' +
    momentsPublishXml(image.thumb_path) + '</local_thumb_url><img_width>' +
    image.width + '</img_width><img_height>' + image.height +
    '</img_height></upload_media>').join('');
  controls.imageXml = makeFixedInput('<publish_data><type>1</type><upload_media_list>' +
    media + '</upload_media_list></publish_data>');
  // makeFixedInput retains its backing allocation in inputStorage; keep a
  // separate reference before the JSON input is used by the adapter.
  controls.imageXmlStorage = controls.inputStorage;
  controls.imageRoot = makeFixedInput('publish_data');
  const parsed = momentsPublishNative(0x601b408, 'bool', ['pointer', 'pointer', 'pointer'])(
    model, controls.imageXml, controls.imageRoot);
  const first = model.add(0xe8).readPointer(), last = model.add(0xf0).readPointer();
  if (!parsed || model.add(0x30).readS32() !== 1 || last.sub(first).toInt32() !== images.length * 16) {
    throw new Error('Native Moments image model did not match prepared images');
  }
  for (let i = 0; i < images.length; i++) {
    const item = first.add(i * 16).readPointer(), image = images[i];
    if (item.isNull() || item.readS32() !== 2 ||
        readCppString(item.add(8)) !== image.client_id ||
        readCppString(item.add(0x20)) !== image.source_path ||
        readCppString(item.add(0x38)) !== image.data_path ||
        readCppString(item.add(0x50)) !== image.thumb_path ||
        item.add(0x68).readFloat() !== image.width || item.add(0x6c).readFloat() !== image.height) {
      throw new Error('Native Moments media fields did not preserve prepared image');
    }
  }
  return model;
}
function momentsPublishPathString(text) {
  // Distinct UTF-8 input for the read-only CDN path checker.
  const bytes = unescape(encodeURIComponent(text)).length;
  const storage = Memory.allocUtf8String(text), value = Memory.alloc(24);
  value.writeByteArray(new Uint8Array(24));
  if (bytes <= 22) { value.writeU8(bytes * 2); value.add(1).writeUtf8String(text); }
  else { value.writeU64(uint64(Math.ceil((bytes + 1) / 16) * 16).or(1)); value.add(8).writeU64(bytes); value.add(16).writePointer(storage); }
  momentsPublishKeepalive.storage.push(storage, value);
  return value;
}
function momentsPublishPathDiagnostics(parameters) {
  const empty = makeFixedInput('');
  const nativeCheck = momentsPublishNative(0x76e7910, 'bool', ['pointer', 'pointer']);
  const paths = (parameters.images || []).map(image => {
    const checks = {};
    ['source_path', 'data_path', 'thumb_path'].forEach(key => {
      checks[key] = nativeCheck(momentsPublishPathString(image[key]), empty);
    });
    return checks;
  });
  return {native_media_roots: [0xa694110, 0xa694128].map(offset =>
    readCppString(momentsPublishKeepalive.mainBase.add(offset))), media_path_checks: paths};
}

function momentsPublishInvokeAdapter(parameters) {
  const controls = momentsPublishKeepalive;
  let hook = null;
  try {
    const prepared = momentsPublishPrepareImages(parameters);
    if (parameters.validate_only === true) {
      const validation = momentsPublishPathDiagnostics(parameters);
      send({kind: 'moments_publish_result', result: Object.assign({success: true, not_submitted: true,
        prepared_media_count: (parameters.images || []).length,
        visibility: parameters.visibility}, validation), error: ''});
      momentsPublishState.completionCount++;
      momentsPublishState.completed = true;
      momentsPublishState.destroyed = true;
      return;
    }
    if (prepared) {
      // The wrapper has created its exact model and copied content/privacy
      // before this call. Move only the already validated image vector into
      // that model; keep the original client id and completion ownership.
      hook = Interceptor.attach(controls.mainBase.add(0x6a181a0), {
        onEnter(args) {
          if (Process.getCurrentThreadId() !== controls.expectedTid ||
              !this.returnAddress.equals(controls.mainBase.add(0x6ccf6e4))) return;
          const model = args[1].readPointer();
          Memory.copy(model.add(0xe8), prepared.add(0xe8), 24);
          prepared.add(0xe8).writeByteArray(new Uint8Array(24));
          model.add(0x30).writeS32(1);
          if (parameters.content.length === 0) model.add(0x58).writeByteArray(new Uint8Array(24));
          momentsPublishState.mediaModelTransfers++;
        }
      });
      Interceptor.flush();
    }
    controls.adapter(ptr(0), controls.input, controls.context, controls.wrapper);
  } finally {
    if (hook) { hook.detach(); Interceptor.flush(); }
    if (controls.imageModel) {
      momentsPublishNative(0x735c25c, 'void', ['pointer'])(controls.imageModel);
      controls.imageModel = null;
    }
  }
}

function validateMomentsPublishImages() {
  momentsPublishValidateEntry(0x76e7910, [0xd10703ff, 0xa9197bfd, 0xa91a57fc, 0xa91b4ff4]);
  momentsPublishValidateEntry(0x601780c, [0xd10743ff, 0xa9177bfd, 0xf900c3fc, 0xa91967fa]);
  momentsPublishValidateEntry(0x601b408, [0xd10483ff, 0xa90f7bfd, 0xa91057fc, 0xa9114ff4]);
  momentsPublishValidateEntry(0x6a181a0, [0xd101c3ff, 0xa9047bfd, 0xf9002bf5, 0xa9064ff4]);
  momentsPublishValidateEntry(0x735c25c, [0xa9be7bfd, 0xf9000bf3, 0x910003fd, 0xf9400413]);
}

rpc.exports = {
  prepare(expectedTid, parameters) {
    if (!Number.isInteger(expectedTid) || expectedTid <= 0) throw new Error("Expected verified executor TID");
    const entry = validateAdapter();
    validateMomentsPublishImages();
    if (!parameters || typeof parameters.content !== 'string' ||
        parameters.content.includes('\0')) {
      throw new Error('Expected Moments content without NUL');
    }
    if (!['public', 'private'].includes(parameters.visibility)) {
      throw new Error('Moments visibility must explicitly be public or private');
    }
    if (parameters.validate_only !== undefined && typeof parameters.validate_only !== 'boolean') throw new Error('Invalid validation flag');
    const images = parameters.images || [];
    if (!Array.isArray(images)) throw new Error('Expected prepared Moments images');
    if (parameters.image_paths && parameters.image_paths.length !== images.length) {
      throw new Error('Image paths must all have corresponding prepared images');
    }
    if (parameters.content.length === 0 && images.length === 0) throw new Error('Expected content or images');
    images.forEach(image => {
      if (!image || !['source_path','data_path','thumb_path','client_id'].every(key =>
          typeof image[key] === 'string' && image[key].length > 0 && !image[key].includes('\0')) ||
          !['source_path','data_path','thumb_path'].every(key => image[key].startsWith('/')) ||
          !Number.isInteger(image.width) || image.width <= 0 ||
          !Number.isInteger(image.height) || image.height <= 0) {
        throw new Error('Invalid prepared Moments image');
      }
    });
    const text = parameters.content;
    for (let i = 0; i < text.length; i++) {
      const code = text.charCodeAt(i);
      if (code >= 0xd800 && code <= 0xdbff) {
        const next = text.charCodeAt(++i);
        if (!(next >= 0xdc00 && next <= 0xdfff)) throw new Error('Unpaired content surrogate');
      } else if (code >= 0xdc00 && code <= 0xdfff) {
        throw new Error('Unpaired content surrogate');
      }
    }
    if (momentsPublishState.prepared) throw new Error('Moments publish task already prepared');
    momentsPublishKeepalive.expectedTid = expectedTid;
    momentsPublishKeepalive.parameters = parameters;
    momentsPublishKeepalive.text = text;

    // ASCII JSON escapes preserve exact Unicode while making native byte length
    // equal to JS string length. This function only allocates data, never sends.
    const json = JSON.stringify({content: text.length === 0 ? ' ' : text, privacy_type: parameters.visibility === 'private' ? 2 : 0, visible_to: []}).replace(
      /[\u007f-\uffff]/g, character => '\\u' + character.charCodeAt(0).toString(16).padStart(4, '0'));
    momentsPublishKeepalive.input = makeFixedInput(json);
    momentsPublishKeepalive.context = Memory.alloc(24);
    momentsPublishKeepalive.context.writeByteArray(new Uint8Array(24));
    momentsPublishKeepalive.callbackObject = Memory.alloc(32);
    momentsPublishKeepalive.callbackObject.writeByteArray(new Uint8Array(32));
    momentsPublishKeepalive.wrapper = Memory.alloc(8);

    momentsPublishKeepalive.invoke = new NativeCallback((self, output, error) => {
      momentsPublishState.completionCount++;
      try {
        if (!self.equals(momentsPublishKeepalive.callbackObject)) {
          throw new Error('Unexpected completion self pointer');
        }
        if (momentsPublishState.completionCount !== 1) throw new Error('Duplicate completion');
        // Native strings are borrowed temporaries: copy during this callback.
        const outputText = readCppString(output);
        const errorText = readCppString(error);
        const result = outputText.length === 0 ? null : JSON.parse(outputText);
        // Native sns ids exceed JS's exact integer range. Preserve the source
        // decimal token before returning the parsed object to Python/MCP.
        if (result && Object.prototype.hasOwnProperty.call(result, 'sns_id')) {
          const snsId = outputText.match(/"sns_id"\s*:\s*(\d+)/);
          if (snsId) result.sns_id = snsId[1];
        }
        send({
          kind: 'moments_publish_result',
          visibility: momentsPublishKeepalive.parameters.visibility,
          media_count: (momentsPublishKeepalive.parameters.images || []).length,
          media_model_transfers: momentsPublishState.mediaModelTransfers,
          result: result,
          raw_json: outputText,
          deliveryConfirmed: false,
          callbackTid: Process.getCurrentThreadId(),
          error: errorText
        });
      } catch (e) {
        recordSendError('completion', e);
        send({kind: 'moments_publish_result', result: null, deliveryConfirmed: false,
          error: 'Completion could not be decoded', errors: momentsPublishState.errors.slice()});
      } finally {
        momentsPublishState.completed = true;
      }
    }, 'void', ['pointer', 'pointer', 'pointer']);

    momentsPublishKeepalive.destroy = new NativeCallback(self => {
      try {
        if (!self.equals(momentsPublishKeepalive.callbackObject)) {
          throw new Error('Unexpected destroy self pointer');
        }
        if (momentsPublishState.destroyed) throw new Error('Duplicate destroy');
        momentsPublishState.destroyed = true;
      } catch (e) {
        recordSendError('destroy', e);
      }
      // Memory.alloc storage belongs to Frida. Never pass it to operator delete.
    }, 'void', ['pointer']);
    momentsPublishKeepalive.query = new NativeCallback((self, kind) => kind !== 0 ? 1 : 0,
      'int', ['pointer', 'int']);

    const object = momentsPublishKeepalive.callbackObject;
    object.writeU32(1); // Native release helper decrements a 32-bit atomic count.
    object.add(8).writePointer(momentsPublishKeepalive.invoke);
    object.add(16).writePointer(momentsPublishKeepalive.destroy);
    object.add(24).writePointer(momentsPublishKeepalive.query);
    momentsPublishKeepalive.wrapper.writePointer(object);
    momentsPublishKeepalive.adapter = new NativeFunction(entry, 'void',
      ['pointer', 'pointer', 'pointer', 'pointer']);

    momentsPublishKeepalive.task = new NativeCallback(userdata => {
      if (momentsPublishState.attempted) {
        recordSendError('task', 'One-shot task invoked more than once; send refused');
        return;
      }
      // Mark before any native call. No retry is permitted even after an error
      // or a wrong-thread refusal; partial native execution cannot be ruled out.
      momentsPublishState.attempted = true;
      if (Process.getCurrentThreadId() !== expectedTid) {
        recordSendError('task', 'Unexpected executor thread; send refused');
        send({kind: 'moments_publish_error', errors: momentsPublishState.errors.slice()});
        return;
      }
      momentsPublishState.invoked = true;
      momentsPublishState.invocationCount++;
      try {
        validateAdapter();
        momentsPublishInvokeAdapter(parameters);
      } catch (e) {
        recordSendError('adapter', e);
        send({kind: 'moments_publish_error', errors: momentsPublishState.errors.slice()});
      }
    }, 'void', ['pointer']);
    momentsPublishState.prepared = true;
    return momentsPublishKeepalive.task.toString();
  },

  status() {
    return {
      prepared: momentsPublishState.prepared,
      attempted: momentsPublishState.attempted,
      visibility: momentsPublishKeepalive.parameters ? momentsPublishKeepalive.parameters.visibility : null,
      contentCodeUnits: momentsPublishKeepalive.text === undefined ? null : momentsPublishKeepalive.text.length,
      invoked: momentsPublishState.invoked,
      completed: momentsPublishState.completed,
      destroyed: momentsPublishState.destroyed,
      invocationCount: momentsPublishState.invocationCount,
      completionCount: momentsPublishState.completionCount,
      mediaModelTransfers: momentsPublishState.mediaModelTransfers,
      errors: momentsPublishState.errors.slice()
    };
  }
};
