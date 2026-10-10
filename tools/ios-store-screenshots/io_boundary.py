"""Reuse frozen descriptor readers; keep controller output beneath owned roots."""
import ast
import types
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import time

REPO = Path(__file__).resolve().parents[2]
DEADLINE = None

def bounded_end(seconds=5):
    now = time.monotonic()
    end = min(now + seconds, DEADLINE if DEADLINE is not None else now + seconds)
    if end <= now:
        raise TimeoutError('Controller file phase expired')
    return end
SOURCE_HASHES = {
    'vision_result_snapshot': '098feb200cb5bbff85f36a7e557114b4e43e95d1271dd9c2f0043541f7440bb3',
    'paired_product_diagnostics': '9a2cb643cf31d82d77e43cb4e720727549882b41859b637362dfd7a693c7c6f1',
    'verify_mac_release_settings': '27ca9bb6c30c24bba96012a84e6c0abcb8e9ec7ff773319c83350ad6ed69f8b2',
}


def bootstrap_source(name):
    """Small bootstrap before trusted descriptor helpers can be imported."""
    if name not in SOURCE_HASHES:
        raise ValueError('Unregistered source module')
    path = REPO / 'scripts' / (name + '.py')
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    end = time.monotonic() + 3
    try:
        for part in path.parent.parts[1:]:
            if time.monotonic() >= end:
                raise TimeoutError('Source bootstrap deadline')
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        file = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        try:
            before = os.fstat(file)
            if not stat.S_ISREG(before.st_mode) or before.st_uid != os.geteuid() or before.st_nlink != 1 or before.st_size > 256_000:
                raise ValueError('Unsafe bootstrap source')
            raw = bytearray()
            while len(raw) <= 256_000:
                if time.monotonic() >= end:
                    raise TimeoutError('Source bootstrap deadline')
                part = os.read(file, min(65536, 256_001 - len(raw)))
                if not part:
                    break
                raw.extend(part)
            after = os.fstat(file)
            if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns) or len(raw) != before.st_size:
                raise ValueError('Bootstrap source changed')
            if hashlib.sha256(raw).hexdigest() != SOURCE_HASHES[name]:
                raise ValueError('Bootstrap source hash differs')
            return bytes(raw)
        finally:
            os.close(file)
    finally:
        os.close(fd)


def load_source(name):
    path = REPO / 'scripts' / (name + '.py')
    raw = bootstrap_source(name)
    value = types.ModuleType('mac_source_' + name)
    value.__file__ = str(path)
    exec(compile(raw, str(path), 'exec'), value.__dict__)
    return value


snapshot = load_source('vision_result_snapshot')
raw_reader = bootstrap_source('paired_product_diagnostics').decode('utf-8')
names = {'_Incomplete', '_check_deadline', '_file_receipt'}
nodes = [node for node in ast.parse(raw_reader).body if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in names]
if {node.name for node in nodes} != names:
    raise ValueError('Frozen descriptor reader shape changed')
namespace = {'os': os, 'stat': stat, 'time': time, 'hashlib': hashlib}
exec(compile(ast.Module(body=nodes, type_ignores=[]), 'frozen_descriptor_reader', 'exec'), namespace)
reader = types.SimpleNamespace(_file_receipt=namespace['_file_receipt'])


def read(path, limit=5_000_000, *, deadline=None):
    path = Path(path).absolute()
    end = min(deadline if deadline is not None else bounded_end(), bounded_end())
    directory = snapshot._open_absolute(path.parent, end, time.monotonic)
    try:
        raw = reader._file_receipt(directory, path.name, os.geteuid(), limit, deadline=end)
        snapshot._anchor(directory, path.parent, end, time.monotonic)
        return raw
    finally:
        os.close(directory)


def mutation_fence(directory, end):
    info = os.fstat(directory)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid():
        raise ValueError('Foreign/non-directory output parent')
    if time.monotonic() >= end:
        raise TimeoutError('Owned file mutation deadline')


def mkdir(path):
    path = Path(path).absolute()
    if path == REPO:
        return
    path.relative_to(REPO)
    missing = []
    here = path
    while not here.exists():
        missing.append(here)
        here = here.parent
    end = bounded_end()
    fd = snapshot._open_absolute(here, end, time.monotonic)
    try:
        for item in reversed(missing):
            mutation_fence(fd, end)
            os.mkdir(item.name, 0o700, dir_fd=fd)
            child = os.open(item.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        if os.fstat(fd).st_uid != os.geteuid():
            raise ValueError('Foreign controller output owner')
        snapshot._anchor(fd, path, end, time.monotonic)
    finally:
        os.close(fd)


def write(path, raw, *, maximum=5_000_000, replace=False):
    path = Path(path).absolute()
    path.relative_to(REPO / 'build')
    if not isinstance(raw, bytes) or len(raw) > maximum:
        raise ValueError('Invalid bounded controller output')
    mkdir(path.parent)
    end = bounded_end()
    directory = snapshot._open_absolute(path.parent, end, time.monotonic)
    temporary = path.name + '.new-' + os.urandom(8).hex()
    descriptor = None
    try:
        if replace:
            try:
                current = os.stat(path.name, dir_fd=directory, follow_symlinks=False)
                if not stat.S_ISREG(current.st_mode) or current.st_uid != os.geteuid() or current.st_nlink != 1:
                    raise ValueError('Unsafe existing output')
            except FileNotFoundError:
                pass
        destination = temporary if replace else path.name
        mutation_fence(directory, end)
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=directory)
        position = 0
        while position < len(raw):
            held = os.fstat(descriptor)
            if not stat.S_ISREG(held.st_mode) or held.st_uid != os.geteuid() or held.st_nlink != 1:
                raise ValueError('Output descriptor ownership changed')
            mutation_fence(directory, end)
            written = os.write(descriptor, raw[position:position + 65536])
            if written <= 0:
                raise OSError('No progress in bounded evidence write')
            position += written
        os.close(descriptor)
        descriptor = None
        snapshot._anchor(directory, path.parent, end, time.monotonic)
        if replace:
            mutation_fence(directory, end)
            os.rename(temporary, path.name, src_dir_fd=directory, dst_dir_fd=directory)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(directory)


def encoded(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, indent=2) + '\n').encode()


def json_read(path, maximum=5_000_000):
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError('Duplicate JSON key')
            value[key] = item
        return value
    return json.loads(read(path, maximum), object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def unlink_owned(path):
    path = Path(path).absolute()
    path.relative_to(REPO / 'build')
    end = bounded_end()
    directory = snapshot._open_absolute(path.parent, end, time.monotonic)
    try:
        info = os.stat(path.name, dir_fd=directory, follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_nlink != 1:
            raise ValueError('Unsafe owned evidence removal')
        snapshot._anchor(directory, path.parent, end, time.monotonic)
        mutation_fence(directory, end)
        os.unlink(path.name, dir_fd=directory)
        snapshot._anchor(directory, path.parent, end, time.monotonic)
    finally:
        os.close(directory)
