/* Experimental ABI probe for the exact ELF documented in research/. No hooks,
 * business dispatch, contacts, messages, network or automatic library loading. */
#define _GNU_SOURCE
#include <stdatomic.h>
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <sys/syscall.h>
#include <unistd.h>

typedef void (*rh_notify)(void *user);
typedef struct {
    _Atomic uint64_t allocations, clones, moves, invokes, destroys, frees;
    _Atomic int64_t last_tid;
    _Atomic uint64_t live_tasks, active_invokes;
} rh_counts;
typedef struct { void *object, *control; } rh_future;
typedef struct {
    const char *file, *function;
    uint32_t line, padding;
    void *caller;
} rh_location;
typedef struct rh_task rh_task;
typedef struct {
    void (*destructor)(rh_task *);
    void (*deleting_destructor)(rh_task *);
    rh_task *(*clone_heap)(const rh_task *);
    void (*clone_into)(const rh_task *, void *);
    void (*destroy)(rh_task *);
    void (*destroy_deallocate)(rh_task *);
    void (*invoke)(rh_task *);
    void *(*target)(rh_task *, const void *);
    const void *(*target_type)(const rh_task *);
} rh_vtable;
/* Itanium __class_type_info has no extra fields beyond type_info. Its vptr is
 * explicitly supplied from the observed client's actual class-type-info object.
 * We do not link a second C++ runtime or reuse the client's lambda type name. */
typedef struct { const void *vptr; const char *name; } rh_type_info;
typedef struct {
    rh_notify notify;
    void *user;
    rh_counts *counts;
    rh_type_info type_info;
} rh_capture;
struct rh_task { const rh_vtable *vptr; rh_capture *capture; };
typedef struct {
    _Alignas(16) unsigned char storage[32];
    rh_task *target;
    unsigned char padding[8];
} rh_function;

_Static_assert(sizeof(void *) == 8, "64-bit pointers required");
_Static_assert(sizeof(rh_location) == 32, "location layout");
_Static_assert(sizeof(rh_future) == 16, "future layout");
_Static_assert(sizeof(rh_function) == 48, "std::function layout");
_Static_assert(offsetof(rh_function, target) == 32, "function target offset");
_Static_assert(sizeof(rh_task) <= 32, "task fits clone_into buffer");
_Static_assert(offsetof(rh_vtable, invoke) == 48, "invoke slot");

static const char rh_type_name[] = "24rh_readonly_noop_capture";
static void count(_Atomic uint64_t *v) {
    atomic_fetch_add_explicit(v, 1, memory_order_relaxed);
}
static void destroy(rh_task *t) {
    count(&t->capture->counts->destroys);
    atomic_fetch_sub_explicit(&t->capture->counts->live_tasks, 1, memory_order_acq_rel);
}
static void destroy_deallocate(rh_task *t) {
    rh_counts *c = t->capture->counts;
    count(&c->destroys);
    count(&c->frees);
    free(t);
    /* Last access to caller-owned state: idle must not become visible while
     * this destructor still needs capture/counts memory. */
    atomic_fetch_sub_explicit(&c->live_tasks, 1, memory_order_acq_rel);
}
static rh_task *clone_heap(const rh_task *t) {
    rh_task *copy = malloc(sizeof *copy);
    /* This C probe cannot throw C++ bad_alloc through client stack frames.
     * Termination on OOM is explicit, never a null callback masquerading as success. */
    if (!copy) abort();
    *copy = *t;
    count(&copy->capture->counts->allocations);
    count(&copy->capture->counts->clones);
    count(&copy->capture->counts->live_tasks);
    return copy;
}
static void clone_into(const rh_task *t, void *buffer) {
    memcpy(buffer, t, sizeof *t);
    count(&t->capture->counts->clones);
    count(&t->capture->counts->live_tasks);
}
static void invoke(rh_task *t) {
    count(&t->capture->counts->active_invokes);
    count(&t->capture->counts->invokes);
    atomic_store_explicit(&t->capture->counts->last_tid,
                          (int64_t)syscall(SYS_gettid), memory_order_release);
    t->capture->notify(t->capture->user);
    atomic_fetch_sub_explicit(&t->capture->counts->active_invokes, 1, memory_order_acq_rel);
}
static void *target(rh_task *t, const void *type) {
    /* Only our exact opaque descriptor is recognized. No foreign RTTI virtual
     * calls or unsafe guesses about string-name equality. */
    return type == &t->capture->type_info ? &t->capture : NULL;
}
static const void *target_type(const rh_task *t) { return &t->capture->type_info; }
static const rh_vtable task_vtable = {
    destroy, destroy_deallocate, clone_heap, clone_into, destroy,
    destroy_deallocate, invoke, target, target_type
};

static void function_destroy(rh_function *f) {
    rh_task *t = f->target;
    f->target = NULL;
    if (!t) return;
    if ((void *)t == (void *)f->storage) t->vptr->destroy(t);
    else t->vptr->destroy_deallocate(t);
}
static int function_init(rh_function *f, rh_capture *capture) {
    memset(f, 0, sizeof *f);
    rh_task *t = malloc(sizeof *t);
    if (!t) return -1;
    t->vptr = &task_vtable;
    t->capture = capture;
    f->target = t;
    count(&capture->counts->allocations);
    count(&capture->counts->live_tasks);
    return 0;
}

/* Assembly adapters preserve the C caller's LR while tail-calling the exact
 * client functions. No target address is resolved or invoked automatically. */
extern void rh_post_x8(void *executor, const rh_location *location,
                       rh_function *function, uint64_t flag,
                       rh_future *out, void *post_address);
extern void rh_location_x8(const char *file, const char *function, uint32_t line,
                          rh_location *out, void *constructor_address);

static void future_release(rh_future *future, void (*weak_release)(void *)) {
    unsigned char *control = future->control;
    future->object = future->control = NULL;
    if (!control) return;
    /* libc++ stores owners minus one. Match 800be64..800be8c exactly. */
    int64_t old = atomic_fetch_sub_explicit((_Atomic int64_t *)(control + 8), 1,
                                           memory_order_acq_rel);
    if (old == 0) {
        void (**vptr)(void *) = *(void (***)(void *))control;
        vptr[2](control); /* on_zero_shared, vtable+16 */
        weak_release(control); /* observed 44c6784, not free(control) */
    }
}

/* Caller owns capture/counts/user/callback and must retain them, this library,
 * and the borrowed RTTI vtable until all tasks/clones/futures have completed.
 * A return of 0 means submitted call returned, never "task completed". */
int rh_submit_tid_probe(void *executor, void *post_address,
                        void *location_constructor,
                        void (*weak_release)(void *), rh_capture *capture) {
    if (!executor || !post_address || !location_constructor || !weak_release ||
        !capture || !capture->notify || !capture->counts || !capture->type_info.vptr)
        return -2;
    capture->type_info.name = rh_type_name;
    rh_function function;
    if (function_init(&function, capture)) return -1;
    static const char file[] = "readonly_executor_shim.c";
    static const char name[] = "rh_submit_tid_probe";
    rh_location location = {0};
    rh_future future = {0};
    rh_location_x8(file, name, 1, &location, location_constructor);
    rh_post_x8(executor, &location, &function, 1, &future, post_address);
    /* Post may move the target away and clear +32, or copy it and leave the
     * source intact. Inspect the actual source wrapper, never free stale t. */
    function_destroy(&function);
    future_release(&future, weak_release);
    return 0;
}

size_t rh_capture_size(void) { return sizeof(rh_capture); }
size_t rh_counts_size(void) { return sizeof(rh_counts); }
void rh_capture_init(rh_capture *c, rh_notify notify, void *user,
                     rh_counts *counts, const void *class_type_info_vptr) {
    *c = (rh_capture){notify, user, counts, {class_type_info_vptr, rh_type_name}};
}
int64_t rh_counts_last_tid(const rh_counts *c) {
    return atomic_load_explicit(&c->last_tid, memory_order_acquire);
}
uint64_t rh_live_tasks(const rh_counts *c) {
    return atomic_load_explicit(&c->live_tasks, memory_order_acquire);
}
int rh_is_idle(const rh_counts *c) {
    return rh_live_tasks(c) == 0 &&
        atomic_load_explicit(&c->active_invokes, memory_order_acquire) == 0;
}
int rh_submit_callback(void *executor, void *post_address,
                        void *location_constructor,
                        void (*weak_release)(void *), rh_notify callback,
                        void *userdata, rh_capture *owned_capture,
                        rh_counts *owned_counts, const void *class_type_info_vptr) {
    if (!owned_capture || !owned_counts || !rh_is_idle(owned_counts)) return -2;
    rh_capture_init(owned_capture, callback, userdata, owned_counts, class_type_info_vptr);
    return rh_submit_tid_probe(executor, post_address, location_constructor,
                               weak_release, owned_capture);
}

#ifdef RH_STANDIN_TEST
#include <assert.h>
#include <stdio.h>
static int observed;
static void notified(void *user) {
    assert(user == &observed);
    observed++;
}
static rh_function queued;
static unsigned mode;
static unsigned zero_shared_calls, weak_calls;
static void zero_shared(void *p) { (void)p; zero_shared_calls++; }
static void weak(void *p) { (void)p; weak_calls++; }
typedef struct { void (**vptr)(void *); _Atomic int64_t strong, weak; } control;
static void (*control_vtable[5])(void *) = {0, 0, zero_shared, 0, 0};
static control future_control;
/* These are stand-ins only. They never call client addresses. */
void rh_location_x8(const char *file, const char *function, uint32_t line,
                    rh_location *out, void *address) {
    (void)address;
    *out = (rh_location){file, function, line, 0, (void *)1};
}
void rh_post_x8(void *executor, const rh_location *location, rh_function *f,
                uint64_t flag, rh_future *out, void *address) {
    assert(executor && address && flag == 1);
    assert(strcmp(location->file, "readonly_executor_shim.c") == 0);
    assert(strcmp(location->function, "rh_submit_tid_probe") == 0);
    memset(&queued, 0, sizeof queued);
    if (mode == 0) { /* heap ownership transfer */
        queued.target = f->target;
        f->target = NULL;
        count(&queued.target->capture->counts->moves);
    } else if (mode == 1) { /* heap clone, source remains owned */
        queued.target = f->target->vptr->clone_heap(f->target);
    } else { /* clone_into inline buffer; source remains owned */
        f->target->vptr->clone_into(f->target, queued.storage);
        queued.target = (rh_task *)queued.storage;
    }
    future_control = (control){control_vtable, mode == 2 ? 1 : 0, 0};
    *out = (rh_future){(void *)1, &future_control};
}
int main(void) {
    rh_counts counts = {0};
    rh_capture capture;
    /* RTTI vptr isn't dereferenced by stand-in. Runtime RTTI remains untested. */
    rh_capture_init(&capture, notified, &observed, &counts, (void *)1);
    for (mode = 0; mode < 3; mode++) {
        assert(rh_submit_callback((void *)1, (void *)1, (void *)1, weak,
            notified, &observed, &capture, &counts, (void *)1) == 0);
        assert(queued.target);
        assert(!rh_is_idle(&counts));
        assert(rh_submit_callback((void *)1, (void *)1, (void *)1, weak,
            notified, &observed, &capture, &counts, (void *)1) == -2);
        assert(queued.target->vptr->target_type(queued.target) == &capture.type_info);
        assert(queued.target->vptr->target(queued.target, &capture.type_info));
        assert(!queued.target->vptr->target(queued.target, NULL));
        queued.target->vptr->invoke(queued.target);
        function_destroy(&queued);
        assert(!queued.target);
        assert(rh_is_idle(&counts));
    }
    assert(observed == 3 && atomic_load(&counts.invokes) == 3);
    assert(rh_counts_last_tid(&counts) > 0);
    assert(atomic_load(&counts.allocations) == atomic_load(&counts.frees));
    assert(atomic_load(&counts.allocations) == 4);
    assert(atomic_load(&counts.destroys) == 5); /* inline clone destroyed too */
    assert(atomic_load(&counts.clones) == 2 && atomic_load(&counts.moves) == 1);
    assert(zero_shared_calls == 2 && weak_calls == 2);
    assert(atomic_load(&future_control.strong) == 0); /* old1 ->0: not last owner */
    puts("PASS: move, clone_heap, clone_into, invoke, source cleanup, future old0/old1");
    return 0;
}
#endif
