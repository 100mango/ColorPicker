"""Owned, byte-copied Vision xcresult input; never run a reader on the source.

``source_binding`` produces the legacy seven-field bundle identity plus two
whole-tree proofs and a source-root anchor in one bounded descriptor-based scan.
``create`` copies and independently verifies under ONE 15-second deadline.
Readers may mutate their private copy: ``verify`` checks its owned anchors,
``verify_input`` checks the initial immutable input, and ``verify_original``
checks the original independently. ``cleanup`` is always bounded to 5 seconds.
No subprocess, copyfile/clone, hardlink, pathname-recursive removal, or reuse of
an existing scratch root is used. Reports contain digests, never tree inventories.
"""
import hashlib
import contextlib
import signal
import math
import os
from pathlib import Path
import stat
import tempfile
import time
import uuid

MAX_FILES = 8192
MAX_DIRECTORIES = 8192
MAX_BYTES = 256 * 1024 * 1024
MAX_PATH_BYTES = 4096
COPY_SECONDS = 15
CLEANUP_SECONDS = 5
LEGACY_KEYS = ('path', 'device', 'inode', 'sha256', 'files', 'directories', 'bytes')
PROOF_KEYS = ('full_tree_sha256', 'node_identity_sha256', 'source_root')
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
_FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK


def _require(value, message):
    if not value:
        raise ValueError(message)


def _end(deadline, clock, seconds=COPY_SECONDS):
    now = clock()
    _require(type(now) in (int, float) and math.isfinite(now), 'Invalid snapshot clock')
    if deadline is None:
        deadline = now + seconds
    _require(type(deadline) in (int, float) and math.isfinite(deadline), 'Invalid snapshot deadline')
    result = min(deadline, now + seconds)
    _check(result, clock)
    return result


def _check(deadline, clock):
    _require(clock() < deadline, 'Snapshot operation exceeded its finite deadline')


def _identity(st):
    return st.st_dev, st.st_ino


def _stamp(st):
    # Reading changes atime on some filesystems, but must not change these fields.
    return (st.st_dev, st.st_ino, st.st_mode, st.st_nlink, st.st_uid,
            st.st_gid, st.st_size, st.st_mtime_ns, st.st_ctime_ns)


def _canonical(path):
    path = Path(path)
    _require(path.is_absolute() and str(path) == os.path.normpath(str(path)), 'Snapshot path is not absolute and canonical')
    _require(len(os.fsencode(str(path))) <= MAX_PATH_BYTES, 'Snapshot path exceeds finite bound')
    _require(path.resolve(strict=True) == path, 'Snapshot path contains an alias')
    return path


def _open_absolute(path, deadline, clock):
    path = _canonical(path)
    fd = os.open('/', _DIR_FLAGS)
    try:
        for name in path.parts[1:]:
            _check(deadline, clock)
            child = os.open(name, _DIR_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = child
        _check(deadline, clock)
        return fd
    except BaseException:
        os.close(fd)
        raise


def _open_relative(root_fd, relative, deadline, clock):
    fd = os.dup(root_fd)
    try:
        for name in relative.split('/') if relative else ():
            _check(deadline, clock)
            _require(name not in ('', '.', '..'), 'Invalid relative snapshot path')
            child = os.open(name, _DIR_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def _anchor(fd, path, deadline, clock):
    actual = _open_absolute(path, deadline, clock)
    try:
        _require(_identity(os.fstat(actual)) == _identity(os.fstat(fd)), 'Snapshot directory path or inode replaced')
    finally:
        os.close(actual)


def _paths(root, bundle):
    root = _canonical(root)
    relative = str(bundle)
    _require(relative and not Path(relative).is_absolute() and
             all(part not in ('', '.', '..') for part in relative.split('/')),
             'Result bundle must have an exact relative path')
    _require(relative.endswith('.xcresult'), 'Snapshot input is not an xcresult bundle')
    path = _canonical(root / relative)
    _require(path.is_relative_to(root) and path != root, 'Result bundle left its source root')
    return root, relative, path


def _record(digest, *fields):
    # Length-prefix each field so even unusual filenames cannot alias a record.
    for field in fields:
        data = os.fsencode(field) if isinstance(field, str) else str(field).encode('ascii')
        digest.update(str(len(data)).encode('ascii') + b':' + data)


def _names(fd, deadline, clock):
    names = []
    with os.scandir(fd) as entries:
        for entry in entries:
            _check(deadline, clock)
            _require(len(names) < MAX_FILES + MAX_DIRECTORIES, 'Snapshot directory entry cap exceeded')
            names.append(entry.name)
    return sorted(names)


def _scan(fd, path, deadline, clock, inventory=None):
    """Independent full read, with the same traversal digest as bundle_identity."""
    if inventory is not None:
        inventory.clear()
        inventory.update(walk_complete=False, observed_files=0, omitted_files=0, records=[])
    nodes = {}
    seen = set()
    legacy = hashlib.sha256()
    count = size = directories = 0
    root_stat = os.fstat(fd)
    pending = ['']
    while pending:
        _check(deadline, clock)
        relative = pending.pop()
        folder_fd = _open_relative(fd, relative, deadline, clock)
        try:
            before = os.fstat(folder_fd)
            directories += 1
            _require(stat.S_ISDIR(before.st_mode) and before.st_dev == root_stat.st_dev and
                     _identity(before) not in seen, 'Unsafe or aliased result directory')
            _require(directories <= MAX_DIRECTORIES, 'Snapshot directory cap exceeded')
            seen.add(_identity(before))
            nodes[relative] = ('directory', _stamp(before), None)
            dirs = []
            files = []
            for name in _names(folder_fd, deadline, clock):
                child_relative = relative + '/' + name if relative else name
                _require(len(os.fsencode(child_relative)) <= MAX_PATH_BYTES, 'Snapshot relative path cap exceeded')
                item = os.stat(name, dir_fd=folder_fd, follow_symlinks=False)
                if stat.S_ISDIR(item.st_mode):
                    dirs.append(child_relative)
                else:
                    _require(stat.S_ISREG(item.st_mode) and item.st_nlink == 1,
                             'Unsafe result file: symlink, hardlink, or special node')
                    files.append((name, child_relative, item))
            for name, child_relative, item in files:
                _check(deadline, clock)
                count += 1
                size += item.st_size
                _require(count <= MAX_FILES and size <= MAX_BYTES, 'Snapshot byte or file cap exceeded')
                _require(item.st_dev == root_stat.st_dev and _identity(item) not in seen,
                         'Result file aliases another node or device')
                seen.add(_identity(item))
                file_fd = os.open(name, _FILE_FLAGS, dir_fd=folder_fd)
                try:
                    _require(_stamp(os.fstat(file_fd)) == _stamp(item), 'Result file replaced before read')
                    legacy.update(child_relative.encode() + b'\0' + str(item.st_size).encode() + b'\0')
                    digest = hashlib.sha256()
                    read = 0
                    while True:
                        _check(deadline, clock)
                        chunk = os.read(file_fd, min(65536, item.st_size - read + 1))
                        if not chunk:
                            break
                        read += len(chunk)
                        _require(read <= item.st_size, 'Result file grew while reading')
                        legacy.update(chunk)
                        digest.update(chunk)
                    _require(read == item.st_size and _stamp(os.fstat(file_fd)) == _stamp(item) and
                             _stamp(os.stat(name, dir_fd=folder_fd, follow_symlinks=False)) == _stamp(item),
                             'Result file mutated or replaced during read')
                    legacy.update(b'\0')
                    nodes[child_relative] = ('file', _stamp(item), digest.hexdigest())
                    if inventory is not None:
                        inventory['observed_files'] += 1
                        if len(inventory['records']) < 256 and len(child_relative.encode()) <= 512:
                            inventory['records'].append({'path': child_relative, 'bytes': item.st_size,
                                'sha256': digest.hexdigest(), 'inode': item.st_ino, 'mtime_ns': str(item.st_mtime_ns)})
                        else:
                            inventory['omitted_files'] += 1
                finally:
                    os.close(file_fd)
            _require(_stamp(os.fstat(folder_fd)) == _stamp(before), 'Result directory changed during traversal')
            pending.extend(reversed(dirs))
        finally:
            os.close(folder_fd)
    _verify_nodes(fd, {name: node[1] for name, node in nodes.items()}, deadline, clock)
    _require(count and 'Info.plist' in nodes and nodes['Info.plist'][0] == 'file', 'Missing completed Vision result bundle')
    _require(_stamp(os.fstat(fd)) == _stamp(root_stat), 'Result root changed during traversal')
    _anchor(fd, path, deadline, clock)
    tree = hashlib.sha256()
    identities = hashlib.sha256()
    for relative in sorted(nodes):
        kind, stamp, digest = nodes[relative]
        _record(tree, relative, kind, stamp[6] if kind == 'file' else '', digest or '')
        _record(identities, relative, kind, *stamp, digest or '')
    result = {'path': str(path), 'device': root_stat.st_dev, 'inode': root_stat.st_ino,
              'sha256': legacy.hexdigest(), 'files': count, 'directories': directories, 'bytes': size,
              'full_tree_sha256': tree.hexdigest(), 'node_identity_sha256': identities.hexdigest()}
    if inventory is not None:
        inventory['walk_complete'] = True
        inventory['identity'] = {key: result[key] for key in LEGACY_KEYS if key != 'path'}
    _check(deadline, clock)
    return result, nodes


def _inspect(fd, path, deadline, clock):
    """Before each reader, reject newly introduced filesystem escape nodes.

    Reader-created ordinary files/directories are allowed, but the entire current
    tree must still fit the original finite bounds. This is metadata-only and
    deliberately does not assert that a previous reader left bytes unchanged.
    """
    root_stat = os.fstat(fd)
    nodes = {}
    seen = set()
    count = directories = size = 0
    pending = ['']
    while pending:
        relative = pending.pop()
        parent = _open_relative(fd, relative, deadline, clock)
        try:
            before = os.fstat(parent)
            directories += 1
            _require(directories <= MAX_DIRECTORIES and before.st_dev == root_stat.st_dev and
                     _identity(before) not in seen, 'Unsafe or aliased private result directory')
            seen.add(_identity(before))
            nodes[relative] = _stamp(before)
            for name in _names(parent, deadline, clock):
                _check(deadline, clock)
                child = relative + '/' + name if relative else name
                _require(len(os.fsencode(child)) <= MAX_PATH_BYTES, 'Private result relative path cap exceeded')
                item = os.stat(name, dir_fd=parent, follow_symlinks=False)
                if stat.S_ISDIR(item.st_mode):
                    pending.append(child)
                    continue
                _require(stat.S_ISREG(item.st_mode) and item.st_nlink == 1 and
                         item.st_dev == root_stat.st_dev and _identity(item) not in seen,
                         'Unsafe private result file: symlink, hardlink, special node, or alias')
                seen.add(_identity(item))
                count += 1
                size += item.st_size
                _require(count <= MAX_FILES and size <= MAX_BYTES, 'Private result byte or file cap exceeded')
                nodes[child] = _stamp(item)
            _require(_stamp(os.fstat(parent)) == _stamp(before), 'Private result directory changed during inspection')
        finally:
            os.close(parent)
    _require('Info.plist' in nodes and stat.S_ISREG(nodes['Info.plist'][2]), 'Missing private completed result bundle')
    _verify_nodes(fd, nodes, deadline, clock)
    _anchor(fd, path, deadline, clock)
    _check(deadline, clock)
    return {'files': count, 'directories': directories, 'bytes': size}


def _verify_nodes(fd, stamps, deadline, clock):
    # Revisit every observed entry, not merely the root. This catches nested
    # replacement after that subtree was visited, including empty directories.
    for relative, expected in stamps.items():
        _check(deadline, clock)
        if not relative:
            actual = os.fstat(fd)
        else:
            folder, _, name = relative.rpartition('/')
            parent = _open_relative(fd, folder, deadline, clock)
            try:
                actual = os.stat(name, dir_fd=parent, follow_symlinks=False)
            finally:
                os.close(parent)
        _require(_stamp(actual) == expected, 'Result node changed after its independent observation')


def _match(actual, expected):
    _require(isinstance(expected, dict) and all(key in expected for key in LEGACY_KEYS), 'Missing original result binding')
    _require(all(actual.get(key) == expected[key] for key in LEGACY_KEYS + PROOF_KEYS if key in expected),
             'Result differs from its original byte/path/node binding')


def source_binding(root, bundle, binding=None, deadline=None, *, clock=time.monotonic, inventory=None):
    """Read original bytes/path identities once; optional old binding must match."""
    deadline = _end(deadline, clock)
    root, relative, path = _paths(root, bundle)
    root_fd = _open_absolute(root, deadline, clock)
    try:
        bundle_fd = _open_relative(root_fd, relative, deadline, clock)
        try:
            result, _ = _scan(bundle_fd, path, deadline, clock, inventory)
            _anchor(root_fd, root, deadline, clock)
            st = os.fstat(root_fd)
            result['source_root'] = {'path': str(root), 'device': st.st_dev, 'inode': st.st_ino}
            if binding is not None:
                _match(result, binding)
            return result
        finally:
            os.close(bundle_fd)
    finally:
        os.close(root_fd)


class OwnedSnapshot:
    """A newly-created scratch root. Never construct one from persisted receipts."""
    def __init__(self, root, bundle, receipt, clock):
        self.source_root = root
        self.bundle = bundle
        self.receipt = receipt
        self.clock = clock
        self.path = self.owned_root = None
        self.identity = self.input_binding = self.original_binding = None
        self._parent_fd = self._owned_fd = self._snapshot_fd = None
        self._owned_identity = self._snapshot_identity = None
        self._closed = False

    def _check_owned(self, deadline, include_snapshot=True):
        _require(not self._closed and self._owned_fd is not None, 'Snapshot ownership is unavailable or stale')
        _anchor(self._parent_fd, self.owned_root.parent, deadline, self.clock)
        current = os.stat(self.owned_root.name, dir_fd=self._parent_fd, follow_symlinks=False)
        _require(stat.S_ISDIR(current.st_mode) and _identity(current) == self._owned_identity and
                 _identity(os.fstat(self._owned_fd)) == self._owned_identity and
                 current.st_uid == os.getuid() and stat.S_IMODE(current.st_mode) == 0o700,
                 'Owned snapshot root is foreign, replaced, or unsafe')
        if include_snapshot:
            current = os.stat(self.path.name, dir_fd=self._owned_fd, follow_symlinks=False)
            _require(stat.S_ISDIR(current.st_mode) and _identity(current) == self._snapshot_identity and
                     _identity(os.fstat(self._snapshot_fd)) == self._snapshot_identity,
                     'Private result bundle root was replaced')
            _anchor(self._snapshot_fd, self.path, deadline, self.clock)

    def verify(self, deadline=None, *, require_input=False):
        """Check owned canonical path/identity, allowing reader-owned byte changes."""
        started = self.clock()
        deadline = _end(deadline, self.clock)
        self._check_owned(deadline)
        if require_input:
            actual,_ = _scan(self._snapshot_fd,self.path,deadline,self.clock)
            _match(actual,self.input_binding)
            inspected={key:actual[key] for key in ('files','directories','bytes')}
            inspected.update(input_byte_equivalent=True,input_binding=dict(self.input_binding))
        else:
            inspected = _inspect(self._snapshot_fd, self.path, deadline, self.clock)
            inspected['input_byte_equivalent']=False
        self._check_owned(deadline)
        self.receipt['reader_input_guard'] = dict(inspected, verified=True, started_at=started, deadline=deadline, finished_at=self.clock())
        return True

    def verify_input(self, deadline=None):
        deadline = _end(deadline, self.clock)
        self._check_owned(deadline)
        actual, _ = _scan(self._snapshot_fd, self.path, deadline, self.clock)
        _match(actual, self.input_binding)
        return actual

    def verify_original(self, deadline=None):
        actual = source_binding(self.source_root, self.bundle, self.original_binding, deadline, clock=self.clock)
        self.receipt['original_guard'] = {'verified': True, 'identity': actual, 'finished_at': self.clock()}
        return actual

    def cleanup(self, deadline=None):
        """Unlink only inside our anchored new root; never follow reader-added links."""
        if self._closed:
            return self.receipt.get('cleanup', {}).get('confirmed') is True
        started = self.clock()
        result = {'started_at': started, 'deadline': None, 'confirmed': False, 'deleted': False}
        self.receipt['cleanup'] = result
        try:
            deadline = _end(deadline, self.clock, CLEANUP_SECONDS)
            result['deadline'] = deadline
            self._check_owned(deadline, include_snapshot=False)
            total = 0
            pending = [('', False, self._owned_identity)]
            while pending:
                relative, visited, expected_identity = pending.pop()
                self._check_owned(deadline, include_snapshot=False)
                fd = _open_relative(self._owned_fd, relative, deadline, self.clock)
                try:
                    current = os.fstat(fd)
                    _require(_identity(current) == expected_identity and current.st_dev == self._owned_identity[0]
                             and current.st_uid == os.getuid(), 'Cleanup directory is foreign or replaced')
                    if visited:
                        if relative:
                            folder, _, name = relative.rpartition('/')
                            parent = _open_relative(self._owned_fd, folder, deadline, self.clock)
                            try:
                                item = os.stat(name, dir_fd=parent, follow_symlinks=False)
                                _require(stat.S_ISDIR(item.st_mode) and _identity(item) == expected_identity,
                                         'Cleanup target replaced')
                                self._check_owned(deadline, include_snapshot=False)
                                _check(deadline, self.clock)
                                os.rmdir(name, dir_fd=parent)
                            finally:
                                os.close(parent)
                        continue
                    pending.append((relative, True, expected_identity))
                    for name in _names(fd, deadline, self.clock):
                        _check(deadline, self.clock)
                        self._check_owned(deadline, include_snapshot=False)
                        # Re-open this parent from the owned root before removal.
                        anchored = _open_relative(self._owned_fd, relative, deadline, self.clock)
                        try:
                            _require(_identity(os.fstat(anchored)) == expected_identity, 'Cleanup parent left owned root')
                        finally:
                            os.close(anchored)
                        total += 1
                        _require(total <= MAX_FILES + MAX_DIRECTORIES + 1, 'Snapshot cleanup entry cap exceeded')
                        item = os.stat(name, dir_fd=fd, follow_symlinks=False)
                        if stat.S_ISDIR(item.st_mode):
                            _require(item.st_dev == self._owned_identity[0] and item.st_uid == os.getuid(),
                                     'Cleanup directory is foreign')
                            pending.append((relative + '/' + name if relative else name, False, _identity(item)))
                        else:
                            # unlink removes this entry, never a symlink target.
                            os.unlink(name, dir_fd=fd)
                finally:
                    os.close(fd)
            self._check_owned(deadline, include_snapshot=False)
            _check(deadline, self.clock)
            os.rmdir(self.owned_root.name, dir_fd=self._parent_fd)
            try:
                os.stat(self.owned_root.name, dir_fd=self._parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise ValueError('Snapshot root still exists after cleanup')
            _check(deadline, self.clock)
            result.update(confirmed=True, deleted=True)
            return True
        except BaseException as error:
            result['error'] = str(error)[:240]
            return False
        finally:
            result['finished_at'] = self.clock()
            self._closed = True
            for name in ('_snapshot_fd', '_owned_fd', '_parent_fd'):
                fd = getattr(self, name)
                if fd is not None:
                    os.close(fd)
                    setattr(self, name, None)


def _copy(source_fd, destination_fd, nodes, deadline, clock):
    # Every destination is new and O_EXCL, with explicit ordinary read/write I/O.
    for relative in sorted(nodes, key=lambda name: (name.count('/'), name)):
        _check(deadline, clock)
        if not relative:
            continue
        kind, stamp, expected_digest = nodes[relative]
        parent, _, name = relative.rpartition('/')
        output_parent = _open_relative(destination_fd, parent, deadline, clock)
        try:
            if kind == 'directory':
                os.mkdir(name, 0o700, dir_fd=output_parent)
                continue
            input_parent = _open_relative(source_fd, parent, deadline, clock)
            try:
                input_fd = os.open(name, _FILE_FLAGS, dir_fd=input_parent)
                try:
                    _require(_stamp(os.fstat(input_fd)) == stamp, 'Source file replaced before byte copy')
                    output_fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=output_parent)
                    try:
                        digest = hashlib.sha256()
                        copied = 0
                        while True:
                            _check(deadline, clock)
                            chunk = os.read(input_fd, min(65536, stamp[6] - copied + 1))
                            if not chunk:
                                break
                            copied += len(chunk)
                            _require(copied <= stamp[6], 'Source file grew while copying')
                            digest.update(chunk)
                            view = memoryview(chunk)
                            while view:
                                _check(deadline, clock)
                                written = os.write(output_fd, view)
                                _require(written > 0, 'Snapshot write made no progress')
                                view = view[written:]
                        _require(copied == stamp[6] and digest.hexdigest() == expected_digest and
                                 _stamp(os.fstat(input_fd)) == stamp and
                                 _stamp(os.stat(name, dir_fd=input_parent, follow_symlinks=False)) == stamp,
                                 'Source bytes or file identity changed while copying')
                        output = os.fstat(output_fd)
                        _require(stat.S_ISREG(output.st_mode) and output.st_nlink == 1 and
                                 _identity(output) != stamp[:2] and output.st_size == copied,
                                 'Snapshot is not an independent ordinary file copy')
                    finally:
                        os.close(output_fd)
                finally:
                    os.close(input_fd)
            finally:
                os.close(input_parent)
        finally:
            os.close(output_parent)


@contextlib.contextmanager
def _anchor_creation_signals():
    # A successful mkdir must have recorded identity and open ownership before
    # normal cancellation is delivered. Do not infer ownership after an error.
    previous=signal.pthread_sigmask(signal.SIG_BLOCK,{signal.SIGTERM,signal.SIGINT})
    try:
        yield
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK,previous)


def create(root, bundle, binding, receipt, deadline, *, clock=time.monotonic):
    """Return an independently verified input, or clean up and raise.

    receipt['snapshot'] is bounded metadata: original_binding, owned_root,
    input_binding, equivalence, verified, state, and cleanup. It survives errors.
    """
    _require(isinstance(receipt, dict), 'Snapshot receipt must be a dictionary')
    info = {'schema': 1, 'state': 'preparing', 'verified': False, 'started_at': clock(),
            'copy_limit_seconds': COPY_SECONDS, 'cleanup_limit_seconds': CLEANUP_SECONDS}
    receipt['snapshot'] = info
    owner = None
    source_fd = None
    try:
        deadline = _end(deadline, clock)
        info['deadline'] = deadline
        root, relative, source_path = _paths(root, bundle)
        owner = OwnedSnapshot(root, relative, info, clock)
        root_fd = _open_absolute(root, deadline, clock)
        try:
            source_fd = _open_relative(root_fd, relative, deadline, clock)
            original, nodes = _scan(source_fd, source_path, deadline, clock)
            _anchor(root_fd, root, deadline, clock)
            st = os.fstat(root_fd)
            original['source_root'] = {'path': str(root), 'device': st.st_dev, 'inode': st.st_ino}
            _match(original, binding)
        finally:
            os.close(root_fd)
        owner.original_binding = original
        info['original_binding'] = dict(original)
        # TMPDIR can itself be an OS alias (notably /var on macOS). Resolve it
        # once, then use only canonical paths and no-follow directory descriptors.
        scratch_parent = Path(tempfile.gettempdir()).resolve(strict=True)
        _require(not scratch_parent.is_relative_to(root), 'Snapshot scratch parent is inside the source/evidence root')
        owner._parent_fd = _open_absolute(scratch_parent, deadline, clock)
        name = 'touchcolor-vision-result-' + uuid.uuid4().hex
        _check(deadline, clock)
        with _anchor_creation_signals():
            info['creation_attempted']=True
            try:
                os.mkdir(name, 0o700, dir_fd=owner._parent_fd)  # existing/stale roots fail
            except FileExistsError:
                info['creation_not_owned']=True
                raise
            owner.owned_root = scratch_parent / name
            created_stat = os.stat(name, dir_fd=owner._parent_fd, follow_symlinks=False)
            owner._owned_identity = _identity(created_stat)
            owner._owned_fd = os.open(name, _DIR_FLAGS, dir_fd=owner._parent_fd)
            owned_stat = os.fstat(owner._owned_fd)
            _require(_identity(owned_stat) == owner._owned_identity, 'Newly owned snapshot root was replaced')
            _require(owned_stat.st_uid == os.getuid() and stat.S_IMODE(owned_stat.st_mode) == 0o700,
                     'New snapshot root is not privately owned')
            info['owned_root'] = {'path': str(owner.owned_root), 'device': owned_stat.st_dev, 'inode': owned_stat.st_ino, 'mode': '0700'}
        owner.path = owner.owned_root / source_path.name
        os.mkdir(owner.path.name, 0o700, dir_fd=owner._owned_fd)
        owner._snapshot_fd = os.open(owner.path.name, _DIR_FLAGS, dir_fd=owner._owned_fd)
        owner._snapshot_identity = _identity(os.fstat(owner._snapshot_fd))
        owner._check_owned(deadline)
        _copy(source_fd, owner._snapshot_fd, nodes, deadline, clock)
        owner._check_owned(deadline)
        snapshot, snapshot_nodes = _scan(owner._snapshot_fd, owner.path, deadline, clock)
        # Independent second reads verify the source and the copy, including
        # empty directories. Do not accept a copy routine's claimed digest.
        after = source_binding(root, relative, original, deadline, clock=clock)
        _require(snapshot['full_tree_sha256'] == original['full_tree_sha256'] and
                 all(snapshot[key] == original[key] for key in ('sha256', 'files', 'directories', 'bytes')),
                 'Snapshot bytes or complete directory structure differ from original')
        _require(not ({stamp[:2] for _, stamp, _ in nodes.values()} &
                      {stamp[:2] for _, stamp, _ in snapshot_nodes.values()}),
                 'Snapshot and source share filesystem identities')
        owner.identity = {key: snapshot[key] for key in LEGACY_KEYS}
        owner.input_binding = dict(snapshot)
        original_guard_finished=clock()
        info.update(state='ready', verified=True, finished_at=clock(), input_binding=dict(snapshot),
                    original_guard={'verified': True, 'identity': after, 'finished_at': original_guard_finished},
                    equivalence={'verified': True, 'ordinary_byte_copy': True, 'independent_readback': True,
                                 'file_identities_disjoint': True, 'full_tree_sha256': snapshot['full_tree_sha256']})
        _check(deadline, clock)
        return owner
    except BaseException as error:
        info.update(state='failed', verified=False, error=str(error)[:240], finished_at=clock())
        if owner is not None and owner._owned_fd is not None:
            owner.cleanup()
        else:
            not_created=not info.get('creation_attempted',False) or info.get('creation_not_owned',False)
            info['cleanup'] = {'confirmed':not_created, 'deleted':False, 'not_created':not_created,
                               'finished_at':clock()}
            if not not_created:
                info['cleanup']['error']='Scratch creation ownership is unconfirmed; no path was adopted or deleted'
            if owner is not None and owner._parent_fd is not None:
                os.close(owner._parent_fd)
                owner._parent_fd = None
        raise
    finally:
        if source_fd is not None:
            os.close(source_fd)
