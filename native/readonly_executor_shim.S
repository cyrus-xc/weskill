#if defined(__aarch64__)
.text
.p2align 2
.global rh_post_x8
.hidden rh_post_x8
.type rh_post_x8, %function
rh_post_x8:
    /* C args x0 executor x1 location x2 wrapper x3 flag x4 out x5 target. */
    mov x8, x4
    br x5
.size rh_post_x8, .-rh_post_x8

.p2align 2
.global rh_location_x8
.hidden rh_location_x8
.type rh_location_x8, %function
rh_location_x8:
    /* x0 file x1 function w2 line x3 out x4 target. */
    mov x8, x3
    br x4
.size rh_location_x8, .-rh_location_x8
.section .note.GNU-stack,"",%progbits
#else
#error This shim only supports AArch64
#endif
