/* Host-only exact-PID identity reader. Compile against the installed macOS SDK.
 * libproc is a private, version-sensitive host API; fail closed on any mismatch.
 * This is not an app component, process scanner, debugger, or memory reader.
 * The caller must bind this identity to its owned device, bundle and time window.
 */
#include <inttypes.h>
#include <libproc.h>
#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/proc_info.h>
#include <unistd.h>

#if PROC_PIDPATHINFO_MAXSIZE < 2 || PROC_PIDPATHINFO_MAXSIZE > 4096
#error Unsupported installed SDK process path bound
#endif

#define JSON_CAP (6 * PROC_PIDPATHINFO_MAXSIZE + 256)

static int unavailable(void)
{
    /* Never echo a supplied argument, a returned path, or an operating-system error. */
    fputs("watch-sample-identity: unavailable\n", stderr);
    return 1;
}

static int decimal_pid(const char *text, int *pid)
{
    unsigned int value = 0;
    size_t length = 0;
    if (text == NULL || text[0] < '1' || text[0] > '9') return 0;
    while (text[length] != '\0') {
        unsigned char c = (unsigned char)text[length];
        if (++length > 7 || c < '0' || c > '9') return 0;
        value = value * 10U + (unsigned int)(c - '0');
        if (value >= 4194304U) return 0;
    }
    if (value <= 1U) return 0;
    *pid = (int)value;
    return 1;
}

static int identity(int pid, uid_t uid, struct proc_bsdinfo *info)
{
    memset(info, 0, sizeof(*info));
    if (sizeof(*info) > INT_MAX ||
        proc_pidinfo(pid, PROC_PIDTBSDINFO, 0, info, (int)sizeof(*info)) != (int)sizeof(*info)) return 0;
    return info->pbi_pid == (uint32_t)pid && info->pbi_uid == uid &&
           info->pbi_start_tvsec > 0 && info->pbi_start_tvsec <= INT64_MAX &&
           info->pbi_start_tvusec < 1000000;
}

static int valid_utf8(const unsigned char *value, size_t length)
{
    size_t i = 0;
    while (i < length) {
        uint32_t code;
        unsigned int count;
        unsigned char first = value[i++];
        if (first < 0x80) continue;
        if (first >= 0xc2 && first <= 0xdf) { count = 1; code = first & 0x1f; }
        else if (first >= 0xe0 && first <= 0xef) { count = 2; code = first & 0x0f; }
        else if (first >= 0xf0 && first <= 0xf4) { count = 3; code = first & 0x07; }
        else return 0;
        if (count > length - i) return 0;
        for (unsigned int n = 0; n < count; ++n) {
            unsigned char next = value[i++];
            if ((next & 0xc0) != 0x80) return 0;
            code = (code << 6) | (next & 0x3f);
        }
        if ((count == 1 && code < 0x80) || (count == 2 && code < 0x800) ||
            (count == 3 && code < 0x10000) || (code >= 0xd800 && code <= 0xdfff) ||
            code > 0x10ffff) return 0;
    }
    return 1;
}

int main(int argc, char **argv)
{
    int pid, returned;
    uid_t uid;
    struct proc_bsdinfo before, after;
    unsigned char path[PROC_PIDPATHINFO_MAXSIZE];
    unsigned char *terminator;
    char output[JSON_CAP];
    size_t used, length;
    static const char hex[] = "0123456789abcdef";

    if (argc != 2 || !decimal_pid(argv[1], &pid)) return unavailable();
    uid = getuid();
    if (geteuid() != uid || !identity(pid, uid, &before)) return unavailable();
    /* A nonzero sentinel detects a missing NUL instead of supplying one ourselves. */
    memset(path, 0xff, sizeof(path));
    returned = proc_pidpath(pid, path, (uint32_t)sizeof(path));
    if (returned <= 1 || returned >= (int)sizeof(path)) return unavailable();
    terminator = memchr(path, '\0', sizeof(path));
    if (terminator == NULL || (size_t)(terminator - path) != (size_t)returned || path[0] != '/') return unavailable();
    length = (size_t)returned;
    if (!valid_utf8(path, length) || !identity(pid, uid, &after)) return unavailable();
    if (before.pbi_pid != after.pbi_pid || before.pbi_uid != after.pbi_uid ||
        before.pbi_start_tvsec != after.pbi_start_tvsec ||
        before.pbi_start_tvusec != after.pbi_start_tvusec || getuid() != uid || geteuid() != uid) return unavailable();

    returned = snprintf(output, sizeof(output),
        "{\"pid\":%d,\"uid\":%" PRIu64 ",\"start_sec\":%" PRIu64 ",\"start_usec\":%" PRIu64 ",\"executable_path\":\"",
        pid, (uint64_t)uid, (uint64_t)before.pbi_start_tvsec, (uint64_t)before.pbi_start_tvusec);
    if (returned < 0 || (size_t)returned >= sizeof(output)) return unavailable();
    used = (size_t)returned;
    for (size_t i = 0; i < length; ++i) {
        unsigned char c = path[i];
        if (sizeof(output) - used < 9) return unavailable();
        if (c < 0x20) {
            output[used++] = '\\'; output[used++] = 'u';
            output[used++] = '0'; output[used++] = '0';
            output[used++] = hex[c >> 4]; output[used++] = hex[c & 0x0f];
        } else {
            if (c == '"' || c == '\\') output[used++] = '\\';
            output[used++] = (char)c;
        }
    }
    output[used++] = '"'; output[used++] = '}'; output[used++] = '\n';
    if (fwrite(output, 1, used, stdout) != used || fflush(stdout) != 0) return unavailable();
    return 0;
}
