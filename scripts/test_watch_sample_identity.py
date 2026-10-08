#!/usr/bin/env python3
"""Synthetic control-flow tests; NOT Darwin SDK, ABI or live-process verification.

The helper is compiled with explicit fake SDK headers and fake libproc/UID
functions. Those stubs return fixtures only and never inspect a real process.
Production compilation must instead use the actual installed macOS SDK headers.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


HEADER = r'''
#ifndef SYNTHETIC_PROC_INFO_H
#define SYNTHETIC_PROC_INFO_H
#include <stdint.h>
#include <sys/types.h>
/* Deliberately synthetic layout: no assertion about the actual Darwin ABI. */
struct proc_bsdinfo {
    uint32_t pbi_pid;
    uid_t pbi_uid;
    uint64_t pbi_start_tvsec;
    uint64_t pbi_start_tvusec;
};
#define PROC_PIDTBSDINFO 314
#define PROC_PIDPATHINFO_MAXSIZE 4096
#endif
'''
LIBPROC = r'''
#include <stdint.h>
#include <sys/proc_info.h>
int proc_pidinfo(int, int, uint64_t, void *, int);
int proc_pidpath(int, void *, uint32_t);
'''
STUB = r'''
#include <libproc.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
static int calls;
static const char *mode(void) {
    const char *v = getenv("SYNTHETIC_IDENTITY_CASE");
    return v ? v : "valid";
}
static int is(const char *v) { return strcmp(mode(), v) == 0; }
static void trace(const char *name, int pid) {
    FILE *f = fopen(getenv("SYNTHETIC_TRACE_PATH"), "a");
    if (!f) abort();
    fprintf(f, "%s %d\n", name, pid);
    fclose(f);
}
uid_t getuid(void) { return 501; }
uid_t geteuid(void) { return is("euid") ? 502 : 501; }
int proc_pidinfo(int pid, int flavor, uint64_t arg, void *buffer, int size) {
    struct proc_bsdinfo info = { (uint32_t)pid, 501, 1791419500, 123456 };
    trace("info", pid);
    if (is("forbid_api") || flavor != PROC_PIDTBSDINFO || arg != 0 || size != (int)sizeof(info)) abort();
    ++calls;
    if (is("info_error")) return 0;
    if (is("info_negative")) return -1;
    if (is("wrong_pid")) ++info.pbi_pid;
    if (is("wrong_uid")) ++info.pbi_uid;
    if (is("zero_sec")) info.pbi_start_tvsec = 0;
    if (is("max_sec")) info.pbi_start_tvsec = UINT64_MAX;
    if (is("bad_usec")) info.pbi_start_tvusec = 1000000;
    if (is("max_usec")) info.pbi_start_tvusec = UINT64_MAX;
    if (is("zero_usec")) info.pbi_start_tvusec = 0;
    if (is("last_usec")) info.pbi_start_tvusec = 999999;
    if (calls == 2) {
        if (is("restart_sec")) ++info.pbi_start_tvsec;
        if (is("restart_usec")) ++info.pbi_start_tvusec;
        if (is("changed_uid")) ++info.pbi_uid;
        if (is("changed_pid")) ++info.pbi_pid;
        if (is("exit")) return 0;
    }
    memcpy(buffer, &info, sizeof(info));
    if (is("short_info")) return (int)sizeof(info) - 1;
    if (is("long_info")) return (int)sizeof(info) + 1;
    return (int)sizeof(info);
}
int proc_pidpath(int pid, void *buffer, uint32_t size) {
    const char *value = "/owned-device/TouchColor.app/TouchColor";
    unsigned char *out = buffer;
    trace("path", pid);
    if (calls != 1 || size != PROC_PIDPATHINFO_MAXSIZE) abort();
    if (is("path_error")) return 0;
    if (is("path_negative")) return -1;
    if (is("relative")) value = "TouchColor";
    if (is("root")) value = "/";
    if (is("empty")) value = "";
    if (is("escaped")) value = "/owned/quote\" slash\\ line\n tab\t control\001";
    if (is("utf8")) value = "/owned/\xe9\xa2\x9c\xe8\x89\xb2/\xf0\x9f\x8e\xa8";
    if (is("utf8_overlong")) value = "/\xc0\xaf";
    if (is("utf8_overlong3")) value = "/\xe0\x80\xaf";
    if (is("utf8_surrogate")) value = "/\xed\xa0\x80";
    if (is("utf8_range")) value = "/\xf4\x90\x80\x80";
    if (is("utf8_short")) value = "/\xe9\xa2";
    if (is("utf8_continuation")) value = "/\x80";
    if (is("utf8_bad_continuation")) value = "/\xe9\x20\x80";
    if (is("no_nul")) { memset(out, 'x', size); out[0] = '/'; return (int)size - 1; }
    if (is("return_full")) { memset(out, 'x', size); out[0] = '/'; return (int)size; }
    if (is("return_oversize")) return (int)size + 1;
    if (is("long_path") || is("long_escaped")) {
        memset(out, is("long_escaped") ? 1 : 'x', size - 1);
        out[0] = '/'; out[size - 1] = 0; return (int)size - 1;
    }
    memcpy(buffer, value, strlen(value) + 1);
    if (is("early_nul")) { out[2] = 0; return (int)strlen(value); }
    if (is("short_return")) return (int)strlen(value) - 1;
    if (is("long_return")) return (int)strlen(value) + 1;
    return (int)strlen(value);
}
'''


class SyntheticIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("cc")
        if compiler is None:
            raise RuntimeError("Synthetic identity tests require an available C compiler")
        cls.temporary = tempfile.TemporaryDirectory(prefix="watch-identity-synthetic-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name)
        sdk = cls.root / "explicit-fake-sdk"
        (sdk / "sys").mkdir(parents=True)
        (sdk / "sys/proc_info.h").write_text(HEADER)
        (sdk / "libproc.h").write_text(LIBPROC)
        stub = cls.root / "synthetic-libproc.c"
        stub.write_text(STUB)
        cls.executable = cls.root / "synthetic-identity"
        source = Path(__file__).with_name("watch_sample_identity.c")
        result = subprocess.run(
            [compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic", "-O2",
             "-I", str(sdk), str(source), str(stub), "-o", str(cls.executable)],
            capture_output=True, timeout=30,
        )
        if result.returncode:
            raise RuntimeError("Synthetic C compilation failed: " + result.stderr.decode("utf-8", "replace"))

    def invoke(self, mode="valid", args=("1234",)):
        trace = self.root / "synthetic-calls.txt"
        trace.unlink(missing_ok=True)
        environment = dict(os.environ, SYNTHETIC_IDENTITY_CASE=mode, SYNTHETIC_TRACE_PATH=str(trace))
        result = subprocess.run([str(self.executable), *args], env=environment, capture_output=True, timeout=3)
        calls = trace.read_text().splitlines() if trace.exists() else []
        self.assertLessEqual(len(result.stdout), 6 * 4096 + 256)
        self.assertLessEqual(len(result.stderr), 64)
        return result, calls

    def reject(self, mode, args=("1234",)):
        result, calls = self.invoke(mode, args)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(result.stderr, b"watch-sample-identity: unavailable\n")
        return calls

    def test_success_exact_pid_only_and_schema(self):
        result, calls = self.invoke()
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, b"")
        self.assertEqual(calls, ["info 1234", "path 1234", "info 1234"])
        self.assertEqual(json.loads(result.stdout), {
            "pid": 1234, "uid": 501, "start_sec": 1791419500, "start_usec": 123456,
            "executable_path": "/owned-device/TouchColor.app/TouchColor",
        })

    def test_pid_argument_rejections_make_no_process_calls(self):
        for args in ((), ("1234", "2"), ("",), ("0",), ("1",), ("4194304",),
                     ("999999999999999999999999999999",), ("-2",), ("+2",), ("02",),
                     (" 2",), ("2 ",), ("2\n",), ("2x",), ("2.0",), ("２",)):
            with self.subTest(args=args):
                self.assertEqual(self.reject("forbid_api", args), [])

    def test_pid_boundaries(self):
        for pid in ("2", "4194303"):
            with self.subTest(pid=pid):
                result, calls = self.invoke(args=(pid,))
                self.assertEqual(result.returncode, 0)
                self.assertEqual(json.loads(result.stdout)["pid"], int(pid))
                self.assertEqual(calls, [f"info {pid}", f"path {pid}", f"info {pid}"])

    def test_elevated_uid_rejected_before_process_read(self):
        self.assertEqual(self.reject("euid"), [])

    def test_bad_initial_identity_never_reads_path(self):
        for mode in ("info_error", "info_negative", "wrong_pid", "wrong_uid", "short_info", "long_info",
                     "zero_sec", "max_sec", "bad_usec", "max_usec"):
            with self.subTest(mode=mode):
                self.assertEqual(self.reject(mode), ["info 1234"])

    def test_valid_start_microsecond_boundaries(self):
        for mode, expected in (("zero_usec", 0), ("last_usec", 999999)):
            with self.subTest(mode=mode):
                result, _ = self.invoke(mode)
                self.assertEqual(result.returncode, 0)
                self.assertEqual(json.loads(result.stdout)["start_usec"], expected)

    def test_exit_restart_and_changed_identity_discard_path(self):
        for mode in ("exit", "restart_sec", "restart_usec", "changed_uid", "changed_pid"):
            with self.subTest(mode=mode):
                self.assertEqual(self.reject(mode), ["info 1234", "path 1234", "info 1234"])

    def test_bad_path_return_and_termination(self):
        for mode in ("path_error", "path_negative", "relative", "root", "empty", "no_nul", "return_full",
                     "return_oversize", "early_nul", "short_return", "long_return"):
            with self.subTest(mode=mode):
                self.assertEqual(self.reject(mode), ["info 1234", "path 1234"])

    def test_json_path_escaping(self):
        result, _ = self.invoke("escaped")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["executable_path"], '/owned/quote" slash\\ line\n tab\t control\x01')
        self.assertEqual(result.stdout.count(b"\n"), 1)

    def test_unicode_path_is_preserved(self):
        result, _ = self.invoke("utf8")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["executable_path"], "/owned/颜色/🎨")

    def test_invalid_utf8_is_fixed_failure(self):
        for mode in ("utf8_overlong", "utf8_overlong3", "utf8_surrogate", "utf8_range", "utf8_short",
                     "utf8_continuation", "utf8_bad_continuation"):
            with self.subTest(mode=mode):
                self.assertEqual(self.reject(mode), ["info 1234", "path 1234"])

    def test_longest_paths_remain_bounded(self):
        for mode, character in (("long_path", "x"), ("long_escaped", "\x01")):
            with self.subTest(mode=mode):
                result, _ = self.invoke(mode)
                self.assertEqual(result.returncode, 0)
                self.assertEqual(json.loads(result.stdout)["executable_path"], "/" + character * 4094)


if __name__ == "__main__":
    unittest.main(verbosity=2)
