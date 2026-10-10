/* Mac-only public SDK bridge. No process creation, signalling, wait or retry. */
#include <errno.h>
#include <stdint.h>
#include <sys/types.h>
#include <libproc.h>
#include <sys/proc_info.h>
#include <signal.h>

enum { TC_CAPACITY = 1024 };
_Static_assert(sizeof(pid_t) == 4, "Unsupported installed public pid_t ABI");

int tc_default_reaper_policy(void) {
    struct sigaction value;
    if (sigaction(SIGCHLD, NULL, &value) != 0) return 0;
    return value.sa_handler == SIG_DFL && !(value.sa_flags & SA_NOCLDWAIT);
}

int tc_owned_group_members(int32_t pgid, int32_t *output, uint32_t capacity,
                           int32_t *saved_errno) {
    if (!output || !saved_errno || pgid <= 0 || capacity != TC_CAPACITY) {
        if (saved_errno) *saved_errno = EINVAL;
        return -1;
    }
    pid_t ids[TC_CAPACITY] = {0};
    errno = 0;
    int bytes = proc_listpids(PROC_PGRP_ONLY, (uint32_t)pgid, ids, sizeof(ids));
    *saved_errno = errno;
    /* Copy only our initialized fixed-size buffer, even for malformed returns. */
    for (uint32_t i = 0; i < TC_CAPACITY; ++i) output[i] = (int32_t)ids[i];
    return bytes;
}
