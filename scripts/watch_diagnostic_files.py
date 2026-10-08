"""Fail-closed local file and PNG primitives for native Watch diagnostics.

These helpers neither export files nor write input bytes. The caller must create
a fresh, private result-export directory under a trusted parent and retain its
ownership for the whole export. Directory inspection is a bounded metadata
snapshot, NOT a filesystem quota or a guarantee about writes between snapshots.

The PNG subset is static, non-interlaced, 8-bit truecolor or truecolor-with-alpha.
Sanitization preserves the exact IHDR/IDAT/IEND chunks and encoded pixel samples.
Removing profiles can change color-managed display; this is not a color renderer.
Reference: https://www.w3.org/TR/png-3/
"""

from __future__ import annotations

import binascii
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import os
import stat
import struct
import zlib


MAX_FILES = 64
MAX_ENTRIES = 128
MAX_DEPTH = 6
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 32 * 1024 * 1024
MAX_PNG_BYTES = 512 * 1024
MAX_PNG_DIMENSION = 1024
MAX_PNG_PIXELS = 1_000_000
MAX_PNG_CHUNKS = 128
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


@dataclass(frozen=True)
class PrivateFile:
    relative_path: str
    size_bytes: int


@dataclass(frozen=True)
class TreeInspection:
    files: tuple[PrivateFile, ...]
    total_bytes: int
    total_entries: int


@dataclass(frozen=True)
class SelectedFile:
    data: bytes
    size_bytes: int
    sha256: str


@dataclass(frozen=True)
class SanitizedPNG:
    data: bytes
    width: int
    height: int
    color_type: int


def _reject(reason: str) -> None:
    # All callers supply a fixed literal, never an input path or payload.
    raise RuntimeError(reason) from None


def _safe_component(name: str) -> bool:
    return (
        isinstance(name, str)
        and bool(name)
        and name not in (".", "..")
        and len(name) <= 255
        and "/" not in name
        and "\\" not in name
        and all(ch.isprintable() and not 0xD800 <= ord(ch) <= 0xDFFF for ch in name)
    )


def _root_path(root: os.PathLike[str] | str) -> str:
    try:
        path = os.fspath(root)
    except (TypeError, ValueError):
        _reject("tree_invalid_root")
    if not isinstance(path, str) or not path or "\x00" in path or "\\" in path:
        _reject("tree_invalid_root")
    if ".." in path.split("/"):
        _reject("tree_invalid_root")
    # Strip trailing separators so O_NOFOLLOW cannot be bypassed by link/.
    while path.endswith("/") or path.endswith("/."):
        path = path[:-1] if path.endswith("/") else path[:-2]
    if not path or path in (".", ".."):
        _reject("tree_invalid_root")
    return path


def _directory_flags() -> int:
    if not all(hasattr(os, attr) for attr in ("O_DIRECTORY", "O_NOFOLLOW", "O_NONBLOCK", "geteuid")):
        _reject("tree_platform_unsupported")
    return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)


def _close_fd(fd: int) -> None:
    try:
        os.close(fd)
    except OSError:
        _reject("tree_io_error")


@contextmanager
def _private_root(root: os.PathLike[str] | str):
    path = _root_path(root)
    flags = _directory_flags()
    fd = None
    try:
        fd = os.open(path, flags)
        info = os.fstat(fd)
        if not stat.S_ISDIR(info.st_mode):
            _reject("tree_invalid_root")
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077:
            _reject("tree_root_not_private")
        yield fd
    except (OSError, ValueError, OverflowError):
        _reject("tree_io_error")
    finally:
        if fd is not None:
            _close_fd(fd)


def _identity(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_nlink,
        info.st_size, info.st_mtime_ns, info.st_ctime_ns,
    )


def _check_entry(info: os.stat_result, root_device: int) -> None:
    if stat.S_ISLNK(info.st_mode):
        _reject("tree_symlink")
    if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
        _reject("tree_special_file")
    if info.st_dev != root_device:
        _reject("tree_cross_device")
    if info.st_uid != os.geteuid():
        _reject("tree_foreign_owner")
    if stat.S_ISREG(info.st_mode):
        if info.st_nlink != 1:
            _reject("tree_hardlink")
        if info.st_size < 0 or info.st_size > MAX_FILE_BYTES:
            _reject("tree_file_bytes_limit")


def _inspect_fd(root_fd: int) -> tuple[TreeInspection, dict[str, tuple[int, ...]]]:
    root_info = os.fstat(root_fd)
    files: list[PrivateFile] = []
    snapshots: dict[str, tuple[int, ...]] = {"": _identity(root_info)}
    directories = {(root_info.st_dev, root_info.st_ino)}
    total_bytes = 0
    total_entries = 0

    def walk(fd: int, prefix: str, depth: int) -> None:
        nonlocal total_bytes, total_entries
        before = os.fstat(fd)
        # Stream entries: never materialize an unbounded directory listing.
        with os.scandir(fd) as entries:
            for entry in entries:
                total_entries += 1
                if total_entries > MAX_ENTRIES:
                    _reject("tree_entries_limit")
                if depth + 1 > MAX_DEPTH:
                    _reject("tree_depth_limit")
                if not _safe_component(entry.name):
                    _reject("tree_unsafe_name")
                info = entry.stat(follow_symlinks=False)
                _check_entry(info, root_info.st_dev)
                relative = prefix + entry.name
                snapshots[relative] = _identity(info)
                if stat.S_ISREG(info.st_mode):
                    if len(files) >= MAX_FILES:
                        _reject("tree_files_limit")
                    total_bytes += info.st_size
                    if total_bytes > MAX_TOTAL_BYTES:
                        _reject("tree_total_bytes_limit")
                    files.append(PrivateFile(relative, info.st_size))
                else:
                    key = (info.st_dev, info.st_ino)
                    if key in directories:
                        _reject("tree_directory_alias")
                    directories.add(key)
                    child_fd = os.open(entry.name, _directory_flags(), dir_fd=fd)
                    try:
                        if _identity(os.fstat(child_fd)) != _identity(info):
                            _reject("tree_changed")
                        walk(child_fd, relative + "/", depth + 1)
                    finally:
                        _close_fd(child_fd)
        if _identity(os.fstat(fd)) != _identity(before):
            _reject("tree_changed")

    walk(root_fd, "", 0)
    if _identity(os.fstat(root_fd)) != _identity(root_info):
        _reject("tree_changed")
    return TreeInspection(tuple(sorted(files, key=lambda f: f.relative_path)),
                          total_bytes, total_entries), snapshots


def inspect_private_tree(root: os.PathLike[str] | str) -> TreeInspection:
    """Inspect only metadata below a caller-created 0700 directory.

    Limits include all descendant entries, with root depth zero. No regular file
    is opened, read, or hashed. Concurrent changes may cause fail-closed rejection.
    The caller must inspect again after its exporting process exits.
    """
    with _private_root(root) as fd:
        return _inspect_fd(fd)[0]


def read_private_file(root: os.PathLike[str] | str, relative_path: str, *, max_bytes: int = MAX_FILE_BYTES) -> SelectedFile:
    """Inspect the entire tree, then securely read/hash one selected regular file.

    Relative paths must match an inspected entry. Directory handles anchor every
    open, links are never followed, and observed replacement/mutation is rejected.
    This is bounded I/O, not protection from a hostile same-user concurrent writer.
    """
    if type(max_bytes) is not int or not 0 <= max_bytes <= MAX_FILE_BYTES:
        _reject("tree_invalid_read_limit")
    if not isinstance(relative_path, str):
        _reject("tree_invalid_relative_path")
    parts = relative_path.split("/")
    if len(parts) > MAX_DEPTH or not all(_safe_component(part) for part in parts):
        _reject("tree_invalid_relative_path")
    with _private_root(root) as root_fd:
        inspection, snapshots = _inspect_fd(root_fd)
        selected = next((item for item in inspection.files
                         if item.relative_path == relative_path), None)
        if selected is None:
            _reject("tree_selection_missing")
        if selected.size_bytes > max_bytes:
            _reject("tree_selection_bytes_limit")
        opened: list[int] = []
        parent_fd = root_fd
        try:
            for index, part in enumerate(parts[:-1], 1):
                fd = os.open(part, _directory_flags(), dir_fd=parent_fd)
                opened.append(fd)
                if _identity(os.fstat(fd)) != snapshots["/".join(parts[:index])]:
                    _reject("tree_changed")
                parent_fd = fd
            flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
            flags |= os.O_NONBLOCK
            fd = os.open(parts[-1], flags, dir_fd=parent_fd)
            opened.append(fd)
            initial = os.fstat(fd)
            _check_entry(initial, os.fstat(root_fd).st_dev)
            if _identity(initial) != snapshots[relative_path]:
                _reject("tree_changed")
            pieces: list[bytes] = []
            count = 0
            digest = hashlib.sha256()
            while True:
                piece = os.read(fd, min(64 * 1024, selected.size_bytes + 1 - count))
                if not piece:
                    break
                count += len(piece)
                if count > selected.size_bytes or count > max_bytes:
                    _reject("tree_changed")
                pieces.append(piece)
                digest.update(piece)
            if count != selected.size_bytes or _identity(os.fstat(fd)) != _identity(initial):
                _reject("tree_changed")
            # Detect renamed/replaced traversal directories before releasing fds.
            if _identity(os.fstat(root_fd)) != snapshots[""]:
                _reject("tree_changed")
            for index, directory_fd in enumerate(opened[:-1], 1):
                if _identity(os.fstat(directory_fd)) != snapshots["/".join(parts[:index])]:
                    _reject("tree_changed")
            return SelectedFile(b"".join(pieces), count, digest.hexdigest())
        finally:
            for fd in reversed(opened):
                _close_fd(fd)


_BEFORE_IDAT = frozenset((b"cHRM", b"gAMA", b"iCCP", b"sBIT", b"sRGB",
                          b"bKGD", b"pHYs", b"sPLT", b"cICP", b"mDCV", b"cLLI"))
_SINGLETON_METADATA = _BEFORE_IDAT - {b"sPLT"} | {b"eXIf", b"tIME"}
_FIXED_METADATA_LENGTHS = {
    b"cHRM": 32, b"gAMA": 4, b"sRGB": 1, b"bKGD": 6, b"pHYs": 9,
    b"tIME": 7, b"cICP": 4, b"mDCV": 24, b"cLLI": 8,
}


def sanitize_native_png(raw: bytes) -> SanitizedPNG:
    """Validate a bounded native screenshot PNG and strip ancillary chunks.

    No image libraries, re-encoding, disk writes, ancillary decompression, or
    pixel modification occur. The single IDAT zlib stream is decoded only up to
    its expected scanline size plus one byte, and every row's filter is checked.
    Animation, palette PNGs, RGB tRNS transparency, and interlacing are rejected.
    """
    if type(raw) is not bytes:
        _reject("png_invalid_input")
    if len(raw) > MAX_PNG_BYTES:
        _reject("png_bytes_limit")
    if not raw.startswith(PNG_SIGNATURE):
        _reject("png_signature")
    position = len(PNG_SIGNATURE)
    chunks = 0
    width = height = color_type = 0
    have_header = have_data = have_end = False
    data_closed = False
    kept = [PNG_SIGNATURE]
    compressed = []
    seen_metadata: set[bytes] = set()
    while position < len(raw):
        chunks += 1
        if chunks > MAX_PNG_CHUNKS:
            _reject("png_chunks_limit")
        if len(raw) - position < 12:
            _reject("png_chunk_length")
        length = struct.unpack_from(">I", raw, position)[0]
        kind = raw[position + 4:position + 8]
        if not all(65 <= value <= 90 or 97 <= value <= 122 for value in kind):
            _reject("png_chunk_type")
        if not 65 <= kind[2] <= 90:
            _reject("png_chunk_type")
        end = position + 12 + length
        if length > MAX_PNG_BYTES or end > len(raw):
            _reject("png_chunk_length")
        payload = raw[position + 8:end - 4]
        expected_crc = struct.unpack_from(">I", raw, end - 4)[0]
        if binascii.crc32(kind + payload) & 0xFFFFFFFF != expected_crc:
            _reject("png_crc")
        if not have_header and kind != b"IHDR":
            _reject("png_chunk_order")
        if kind == b"IHDR":
            if have_header or chunks != 1:
                _reject("png_chunk_order")
            if length != 13:
                _reject("png_header_length")
            width, height, bits, color_type, compression, filtering, interlace = struct.unpack(
                ">IIBBBBB", payload)
            if not (1 <= width <= MAX_PNG_DIMENSION and 1 <= height <= MAX_PNG_DIMENSION):
                _reject("png_dimensions")
            if width * height > MAX_PNG_PIXELS:
                _reject("png_pixels_limit")
            if bits != 8 or color_type not in (2, 6) or compression != 0 or filtering != 0 or interlace != 0:
                _reject("png_unsupported_format")
            have_header = True
            kept.append(raw[position:end])
        elif kind == b"IDAT":
            if data_closed:
                _reject("png_chunk_order")
            have_data = True
            compressed.append(payload)
            kept.append(raw[position:end])
        elif kind == b"IEND":
            if not have_data or length != 0 or end != len(raw):
                _reject("png_chunk_order")
            have_end = True
            kept.append(raw[position:end])
        else:
            if not kind[0] & 0x20:
                _reject("png_unsupported_critical_chunk")
            if kind in (b"tRNS", b"acTL", b"fcTL", b"fdAT", b"hIST"):
                _reject("png_unsupported_format")
            if have_data:
                data_closed = True
                if kind in _BEFORE_IDAT:
                    _reject("png_chunk_order")
            if kind in _SINGLETON_METADATA:
                if kind in seen_metadata:
                    _reject("png_chunk_order")
                seen_metadata.add(kind)
            required = _FIXED_METADATA_LENGTHS.get(kind)
            if required is not None and length != required:
                _reject("png_metadata_length")
            if kind == b"sBIT" and length != (3 if color_type == 2 else 4):
                _reject("png_metadata_length")
            if b"iCCP" in seen_metadata and b"sRGB" in seen_metadata:
                _reject("png_chunk_order")
        position = end
    if not (have_header and have_data and have_end):
        _reject("png_incomplete")
    channels = 3 if color_type == 2 else 4
    row_bytes = 1 + width * channels
    expected_bytes = height * row_bytes
    try:
        decoder = zlib.decompressobj()
        pixels = decoder.decompress(b"".join(compressed), expected_bytes + 1)
    except zlib.error:
        _reject("png_zlib_invalid")
    if len(pixels) > expected_bytes or decoder.unconsumed_tail:
        _reject("png_decompression_limit")
    if not decoder.eof or decoder.unused_data or len(pixels) != expected_bytes:
        _reject("png_zlib_invalid")
    if any(pixels[offset] > 4 for offset in range(0, expected_bytes, row_bytes)):
        _reject("png_filter_invalid")
    return SanitizedPNG(b"".join(kept), width, height, color_type)
