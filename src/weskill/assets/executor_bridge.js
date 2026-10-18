
const bridgeKeepalive = {};
const queryExports = rpc.exports;
let bridgeNoopRuns = 0;
const bridgeExports = {
  setup(path) {
    if (Process.arch !== 'arm64') throw new Error('Expected ARM64');
    const main = Process.getModuleByName('wechat');
    if (main.base.add(0x60d0614).readU32() !== 0xd106c3ff) throw new Error('Post prologue mismatch');
    const app = main.base.add(0xa68fbc0).readPointer();
    const executor = app.add(0x290).readPointer();
    if (executor.isNull()) throw new Error('Application executor is null');
    const module = Module.load(path);
    const fn = (name, ret, args) => new NativeFunction(module.getExportByName(name), ret, args);
    const countSize = fn('rh_counts_size', 'uint64', [])().toNumber();
    const captureSize = fn('rh_capture_size', 'uint64', [])().toNumber();
    const counts = Memory.alloc(countSize);
    counts.writeByteArray(new Uint8Array(countSize));
    const capture = Memory.alloc(captureSize);
    const submit = fn('rh_submit_callback', 'int', Array(9).fill('pointer'));
    const idle = fn('rh_is_idle', 'int', ['pointer']);
    const live = fn('rh_live_tasks', 'uint64', ['pointer']);
    const tid = fn('rh_counts_last_tid', 'int64', ['pointer']);
    const noop = new NativeCallback(user => {
      bridgeNoopRuns++;
      send({kind: 'executor_noop', tid: Process.getCurrentThreadId()});
    }, 'void', ['pointer']);
    Object.assign(bridgeKeepalive, {main, executor, module, counts, capture, submit, idle, live, tid, noop});
    return {callerTid: Process.getCurrentThreadId(), countSize, captureSize};
  },
  submitTask(task) {
    const b = bridgeKeepalive;
    if (!b.idle(b.counts)) throw new Error('Executor probe is still active');
    const callback = task === null ? b.noop : ptr(task);
    return b.submit(b.executor, b.main.base.add(0x60d0614), b.main.base.add(0x44cdfec),
      b.main.base.add(0x44c6784), callback, ptr(0), b.capture, b.counts,
      b.main.base.add(0xa336170).readPointer());
  },
  bridgeStatus() {
    const b = bridgeKeepalive;
    return {idle: b.idle(b.counts) !== 0, live: b.live(b.counts).toString(),
      tid: b.tid(b.counts).toString(), invokes: b.counts.add(24).readU64().toString(),
      allocations: b.counts.readU64().toString(), frees: b.counts.add(40).readU64().toString(),
      noopRuns: bridgeNoopRuns};
  }
};
rpc.exports = Object.assign({}, queryExports, bridgeExports);
