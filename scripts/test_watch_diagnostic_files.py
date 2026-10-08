"""Offline stdlib-only tests. Run with both python3 -B and python3 -B -O."""

import binascii
import hashlib
import os
from pathlib import Path
import stat
import struct
import tempfile
import unittest
from unittest import mock
import zlib

import watch_diagnostic_files as files


def chunk(kind, payload=b""):
    return (struct.pack(">I", len(payload)) + kind + payload
            + struct.pack(">I", binascii.crc32(kind + payload) & 0xFFFFFFFF))


def header(width=2, height=2, bits=8, color=6, compression=0, filtering=0, interlace=0):
    return chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, bits, color,
                                      compression, filtering, interlace))


def png(width=2, height=2, color=6, pixels=None, before=(), after=(), compressed=None):
    if pixels is None:
        row_size = width * (3 if color == 2 else 4)
        pixels = (b"\x00" + b"\x31" * row_size) * height
    if compressed is None:
        compressed = zlib.compress(pixels)
    return (files.PNG_SIGNATURE + header(width, height, color=color)
            + b"".join(before) + chunk(b"IDAT", compressed)
            + b"".join(after) + chunk(b"IEND"))


def chunks(raw):
    position = 8
    result = []
    while position < len(raw):
        length = struct.unpack_from(">I", raw, position)[0]
        result.append((raw[position + 4:position + 8], raw[position:position + 12 + length]))
        position += 12 + length
    return result


class TreeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "export"
        self.root.mkdir(mode=0o700)

    def write(self, name, content=b"native"):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def sparse(self, name, size):
        path = self.root / name
        with path.open("wb") as stream:
            stream.truncate(size)
        return path

    def rejected(self, reason, function=files.inspect_private_tree, *args):
        with self.assertRaisesRegex(RuntimeError, "^" + reason + "$"):
            function(*(args or (self.root,)))

    def test_empty_private_tree(self):
        self.assertEqual(files.inspect_private_tree(self.root), files.TreeInspection((), 0, 0))

    def test_sorted_inventory_and_selected_hash(self):
        self.write("nested/z.png", b"abc")
        self.write("a.png", b"defg")
        report = files.inspect_private_tree(self.root)
        self.assertEqual(report.files, (files.PrivateFile("a.png", 4),
                                        files.PrivateFile("nested/z.png", 3)))
        self.assertEqual((report.total_bytes, report.total_entries), (7, 3))
        selected = files.read_private_file(self.root, "nested/z.png")
        self.assertEqual(selected, files.SelectedFile(b"abc", 3, hashlib.sha256(b"abc").hexdigest()))

    def test_inventory_never_reads_or_hashes_regular_files(self):
        self.write("shot.png", b"data")
        with mock.patch.object(files.os, "read", side_effect=AssertionError("unexpected read")), \
                mock.patch.object(files.hashlib, "sha256", side_effect=AssertionError("unexpected hash")):
            self.assertEqual(files.inspect_private_tree(self.root).total_bytes, 4)

    def test_empty_file_read(self):
        self.write("empty", b"")
        self.assertEqual(files.read_private_file(self.root, "empty").size_bytes, 0)

    def test_root_must_be_private(self):
        self.root.chmod(0o750)
        self.rejected("tree_root_not_private")

    def test_root_must_be_directory(self):
        target = self.write("regular")
        self.rejected("tree_io_error", files.inspect_private_tree, target)

    def test_invalid_roots(self):
        for value in (None, b"bytes", "", "/", ".", "..", "a/../b", "a\x00b", "a\\b"):
            with self.subTest(value=value):
                self.rejected("tree_invalid_root", files.inspect_private_tree, value)

    def test_parent_traversal_even_when_existing(self):
        path = str(self.root / ".." / "export")
        self.rejected("tree_invalid_root", files.inspect_private_tree, path)

    def test_missing_root_errors_do_not_reveal_path(self):
        secret_path = self.root / "customer-sensitive-name"
        self.rejected("tree_io_error", files.inspect_private_tree, secret_path)

    def test_close_errors_are_fixed_and_redacted(self):
        real_close = os.close

        def failing_close(fd):
            real_close(fd)
            raise OSError("customer-sensitive-name")

        with mock.patch.object(files.os, "close", side_effect=failing_close):
            self.rejected("tree_io_error")

    def test_foreign_owner_and_cross_device_rejected(self):
        foreign = mock.Mock(st_mode=stat.S_IFREG | 0o600, st_dev=1,
                            st_uid=os.geteuid() + 1)
        self.rejected("tree_foreign_owner", files._check_entry, foreign, 1)
        cross_device = mock.Mock(st_mode=stat.S_IFDIR | 0o700, st_dev=2)
        self.rejected("tree_cross_device", files._check_entry, cross_device, 1)

    def test_root_symlink_with_trailing_separators(self):
        link = self.root.parent / "link"
        link.symlink_to(self.root, target_is_directory=True)
        for suffix in ("", "/", "/.", "/./"):
            with self.subTest(suffix=suffix):
                self.rejected("tree_io_error", files.inspect_private_tree, str(link) + suffix)

    def test_child_symlink_is_rejected(self):
        (self.root / "link").symlink_to(self.root.parent)
        self.rejected("tree_symlink")

    def test_dangling_symlink_is_rejected(self):
        (self.root / "link").symlink_to("missing")
        self.rejected("tree_symlink")

    def test_hardlink_is_rejected(self):
        outside = self.root.parent / "outside"
        outside.write_bytes(b"secret")
        os.link(outside, self.root / "link")
        self.rejected("tree_hardlink")

    def test_internal_hardlink_is_rejected(self):
        source = self.write("first")
        os.link(source, self.root / "second")
        self.rejected("tree_hardlink")

    def test_fifo_is_rejected_without_opening(self):
        os.mkfifo(self.root / "fifo")
        self.rejected("tree_special_file")

    def test_socket_and_device_modes_are_rejected(self):
        # No socket creation is needed or permitted in the local test sandbox.
        # FIFO coverage above uses a real filesystem entry; these cover stat modes.
        for kind in (stat.S_IFSOCK, stat.S_IFCHR, stat.S_IFBLK):
            with self.subTest(kind=kind):
                info = mock.Mock(st_mode=kind | 0o600)
                self.rejected("tree_special_file", files._check_entry, info, 0)

    def test_safe_and_unsafe_names(self):
        self.write("截图 1.png")
        self.assertEqual(files.inspect_private_tree(self.root).files[0].relative_path, "截图 1.png")
        for name in ("bad\nname", "bad\\name", "bad\tname", "bad\x1bname"):
            with self.subTest(name=name):
                path = self.write(name)
                self.rejected("tree_unsafe_name")
                path.unlink()

    def test_depth_boundary(self):
        self.write("a/b/c/d/e/shot.png")
        self.assertEqual(files.inspect_private_tree(self.root).total_entries, 6)
        self.write("a/b/c/d/e/f/shot.png")
        self.rejected("tree_depth_limit")

    def test_empty_directory_depth_boundary(self):
        deepest = self.root / "a/b/c/d/e/f"
        deepest.mkdir(parents=True)
        self.assertEqual(files.inspect_private_tree(self.root).total_entries, 6)
        (deepest / "g").mkdir()
        self.rejected("tree_depth_limit")

    def test_file_count_boundary(self):
        for index in range(files.MAX_FILES):
            self.write(str(index), b"")
        self.assertEqual(len(files.inspect_private_tree(self.root).files), 64)
        self.write("excess", b"")
        self.rejected("tree_files_limit")

    def test_entry_count_boundary(self):
        for index in range(files.MAX_ENTRIES):
            (self.root / str(index)).mkdir()
        self.assertEqual(files.inspect_private_tree(self.root).total_entries, 128)
        (self.root / "excess").mkdir()
        self.rejected("tree_entries_limit")

    def test_single_file_size_boundary(self):
        path = self.sparse("large", files.MAX_FILE_BYTES)
        self.assertEqual(files.inspect_private_tree(self.root).total_bytes, files.MAX_FILE_BYTES)
        with path.open("ab") as stream:
            stream.write(b"x")
        self.rejected("tree_file_bytes_limit")

    def test_total_size_boundary(self):
        for index in range(4):
            self.sparse(str(index), files.MAX_FILE_BYTES)
        self.assertEqual(files.inspect_private_tree(self.root).total_bytes, files.MAX_TOTAL_BYTES)
        self.write("extra", b"x")
        self.rejected("tree_total_bytes_limit")

    def test_selected_paths_are_strict_relative_paths(self):
        self.write("good", b"x")
        for path in (None, "", ".", "..", "../good", "/good", "a/../good", "a//good",
                     "./good", "good/", "good\\bad", "bad\nname", "a/b/c/d/e/f/g"):
            with self.subTest(path=path):
                self.rejected("tree_invalid_relative_path", files.read_private_file, self.root, path)

    def test_selected_file_must_exist(self):
        self.rejected("tree_selection_missing", files.read_private_file, self.root, "absent")

    def test_selected_directory_is_not_a_file(self):
        (self.root / "directory").mkdir()
        self.rejected("tree_selection_missing", files.read_private_file, self.root, "directory")

    def test_selected_read_rechecks_whole_tree(self):
        self.write("good")
        self.sparse("oversize", files.MAX_FILE_BYTES + 1)
        self.rejected("tree_file_bytes_limit", files.read_private_file, self.root, "good")

    def test_replacement_symlink_before_selected_open(self):
        target = self.write("good")
        real_open = os.open

        def swapping_open(path, flags, *args, **kwargs):
            if path == "good":
                target.unlink()
                target.symlink_to(self.root.parent)
            return real_open(path, flags, *args, **kwargs)

        with mock.patch.object(files.os, "open", side_effect=swapping_open):
            self.rejected("tree_io_error", files.read_private_file, self.root, "good")

    def test_mutation_before_selected_open(self):
        target = self.write("good")
        real_open = os.open

        def changing_open(path, flags, *args, **kwargs):
            if path == "good":
                target.write_bytes(b"changed-and-larger")
            return real_open(path, flags, *args, **kwargs)

        with mock.patch.object(files.os, "open", side_effect=changing_open):
            self.rejected("tree_changed", files.read_private_file, self.root, "good")

    def test_mutation_during_selected_read(self):
        target = self.write("good")
        real_read = os.read
        changed = False

        def changing_read(fd, amount):
            nonlocal changed
            if not changed:
                changed = True
                with target.open("ab") as stream:
                    stream.write(b"changed")
            return real_read(fd, amount)

        with mock.patch.object(files.os, "read", side_effect=changing_read):
            self.rejected("tree_changed", files.read_private_file, self.root, "good")

    def test_shortening_during_selected_read(self):
        target = self.write("good")
        real_read = os.read

        def changing_read(fd, amount):
            target.write_bytes(b"")
            return real_read(fd, amount)

        with mock.patch.object(files.os, "read", side_effect=changing_read):
            self.rejected("tree_changed", files.read_private_file, self.root, "good")

    def test_bounded_selected_read_calls(self):
        self.write("good", b"x" * (128 * 1024))
        real_read = os.read
        amounts = []

        def tracking_read(fd, amount):
            amounts.append(amount)
            return real_read(fd, amount)

        with mock.patch.object(files.os, "read", side_effect=tracking_read):
            selected = files.read_private_file(self.root, "good")
        self.assertEqual(selected.size_bytes, 128 * 1024)
        self.assertEqual(amounts, [65536, 65536, 1])


class PNGTests(unittest.TestCase):
    def rejected(self, reason, data):
        with self.assertRaisesRegex(RuntimeError, "^" + reason + "$"):
            files.sanitize_native_png(data)

    def test_rgb_and_rgba_unchanged(self):
        for color in (2, 6):
            with self.subTest(color=color):
                raw = png(color=color)
                clean = files.sanitize_native_png(raw)
                self.assertEqual(clean, files.SanitizedPNG(raw, 2, 2, color))

    def test_metadata_removed_and_encoded_pixel_bytes_unchanged(self):
        raw = png(before=(chunk(b"tEXt", b"private-name\0private-value"),
                          chunk(b"gAMA", struct.pack(">I", 45455)),
                          chunk(b"eXIf", b"private-exif"),
                          chunk(b"iCCP", b"profile\0\0compressed-not-inflated")),
                  after=(chunk(b"iTXt", b"private trailing comment"),))
        result = files.sanitize_native_png(raw)
        original_critical = [encoded for kind, encoded in chunks(raw)
                             if kind in (b"IHDR", b"IDAT", b"IEND")]
        self.assertEqual(result.data, files.PNG_SIGNATURE + b"".join(original_critical))
        self.assertNotIn(b"private", result.data)
        original_idat = b"".join(encoded[8:-4] for kind, encoded in chunks(raw) if kind == b"IDAT")
        clean_idat = b"".join(encoded[8:-4] for kind, encoded in chunks(result.data) if kind == b"IDAT")
        self.assertEqual(original_idat, clean_idat)
        self.assertEqual(zlib.decompress(original_idat), zlib.decompress(clean_idat))

    def test_unknown_ancillary_removed(self):
        self.assertEqual(files.sanitize_native_png(png(before=(chunk(b"vpAg", b"unknown"),))).data, png())

    def test_idat_split_at_any_boundary_and_empty_chunks(self):
        data = zlib.compress((b"\0" + b"\x31" * 8) * 2)
        for index in range(len(data) + 1):
            raw = (files.PNG_SIGNATURE + header() + chunk(b"IDAT", data[:index])
                   + chunk(b"IDAT") + chunk(b"IDAT", data[index:]) + chunk(b"IEND"))
            with self.subTest(index=index):
                self.assertEqual(files.sanitize_native_png(raw).data, raw)

    def test_all_standard_filter_bytes_accepted(self):
        pixels = b"".join(bytes([index]) + bytes(range(8)) for index in range(5))
        self.assertEqual(files.sanitize_native_png(png(height=5, pixels=pixels)).height, 5)

    def test_invalid_filter_byte_rejected(self):
        for position in (0, 9):
            pixels = bytearray((b"\0" + b"\x31" * 8) * 2)
            pixels[position] = 5
            self.rejected("png_filter_invalid", png(pixels=bytes(pixels)))

    def test_invalid_input_type(self):
        for value in (None, "PNG", bytearray(png()), memoryview(png())):
            self.rejected("png_invalid_input", value)

    def test_signature_and_unknown_formats(self):
        for value in (b"", b"\xff\xd8JPEG", b"GIF89a", b"%PDF-1.7", b"\x89PNG\n\r\x1a\n"):
            self.rejected("png_signature", value)

    def test_every_truncation_rejected(self):
        raw = png()
        for index in range(len(raw)):
            with self.subTest(index=index), self.assertRaises(RuntimeError):
                files.sanitize_native_png(raw[:index])

    def test_crc_damage_in_critical_and_stripped_metadata(self):
        for kind in (b"IHDR", b"IDAT", b"IEND", b"tEXt"):
            raw = bytearray(png(before=(chunk(b"tEXt", b"key\0value"),)))
            offset = raw.index(kind)
            length = struct.unpack_from(">I", raw, offset - 4)[0]
            raw[offset + 4 + length] ^= 1
            self.rejected("png_crc", bytes(raw))

    def test_declared_chunk_length_overflow(self):
        raw = files.PNG_SIGNATURE + struct.pack(">I", 0xFFFFFFFF) + b"IHDR" + b"x" * 20
        self.rejected("png_chunk_length", raw)

    def test_header_length(self):
        self.rejected("png_header_length", files.PNG_SIGNATURE + chunk(b"IHDR", b"bad"))

    def test_header_must_be_first_and_unique(self):
        self.rejected("png_chunk_order", files.PNG_SIGNATURE + chunk(b"tEXt", b"text") + png()[8:])
        self.rejected("png_chunk_order", files.PNG_SIGNATURE + header() + png()[8:])

    def test_idat_must_be_consecutive(self):
        data = zlib.compress((b"\0" + b"x" * 8) * 2)
        raw = (files.PNG_SIGNATURE + header() + chunk(b"IDAT", data[:3])
               + chunk(b"tEXt", b"metadata") + chunk(b"IDAT", data[3:]) + chunk(b"IEND"))
        self.rejected("png_chunk_order", raw)

    def test_ancillary_order_and_duplicate_metadata(self):
        gamma = chunk(b"gAMA", struct.pack(">I", 45455))
        self.rejected("png_chunk_order", png(after=(gamma,)))
        self.rejected("png_chunk_order", png(before=(gamma, gamma)))
        self.rejected("png_chunk_order", png(before=(chunk(b"sRGB", b"\0"), chunk(b"iCCP", b"profile"))))

    def test_ancillary_fixed_length(self):
        for kind in (b"gAMA", b"sRGB", b"pHYs", b"sBIT"):
            with self.subTest(kind=kind):
                self.rejected("png_metadata_length", png(before=(chunk(kind, b"wrong-length"),)))

    def test_chunk_type_letters_and_reserved_bit(self):
        for kind in (b"t1Xt", b"texT", b"\xffEXt"):
            self.rejected("png_chunk_type", png(before=(chunk(kind),)))

    def test_unknown_critical_and_palette_rejected(self):
        for kind in (b"ABCD", b"CgBI", b"PLTE"):
            self.rejected("png_unsupported_critical_chunk", png(before=(chunk(kind),)))

    def test_animation_and_transparency_rejected(self):
        for kind in (b"acTL", b"fcTL", b"fdAT", b"tRNS", b"hIST"):
            self.rejected("png_unsupported_format", png(before=(chunk(kind),)))

    def test_unsupported_pixel_formats(self):
        configurations = ({"bits": 16}, {"bits": 1}, {"color": 0}, {"color": 3},
                          {"color": 4}, {"compression": 1}, {"filtering": 1}, {"interlace": 1})
        for configuration in configurations:
            with self.subTest(configuration=configuration):
                self.rejected("png_unsupported_format", files.PNG_SIGNATURE + header(**configuration))

    def test_dimension_bounds(self):
        for width, height in ((0, 2), (2, 0), (1025, 2), (2, 1025), (0xFFFFFFFF, 1)):
            self.rejected("png_dimensions", files.PNG_SIGNATURE + header(width=width, height=height))
        self.assertEqual(files.sanitize_native_png(png(width=1, height=1024)).height, 1024)
        self.assertEqual(files.sanitize_native_png(png(width=1024, height=1)).width, 1024)

    def test_pixel_count_limit(self):
        self.rejected("png_pixels_limit", files.PNG_SIGNATURE + header(width=1024, height=1024))
        self.assertEqual(files.sanitize_native_png(png(width=1000, height=1000)).width, 1000)

    def test_encoded_byte_limit(self):
        overhead = len(png()) + 12
        exact = png(before=(chunk(b"vpAg", b"x" * (files.MAX_PNG_BYTES - overhead)),))
        self.assertEqual(len(exact), files.MAX_PNG_BYTES)
        self.assertEqual(files.sanitize_native_png(exact).data, png())
        self.rejected("png_bytes_limit", exact + b"x")

    def test_chunk_count_limit(self):
        allowed = png(before=(chunk(b"tEXt") for _ in range(files.MAX_PNG_CHUNKS - 3)))
        self.assertEqual(files.sanitize_native_png(allowed).data, png())
        excessive = png(before=(chunk(b"tEXt") for _ in range(files.MAX_PNG_CHUNKS - 2)))
        self.rejected("png_chunks_limit", excessive)

    def test_missing_idat_or_iend(self):
        self.rejected("png_chunk_order", files.PNG_SIGNATURE + header() + chunk(b"IEND"))
        self.rejected("png_incomplete", png()[:-12])
        self.rejected("png_incomplete", files.PNG_SIGNATURE)

    def test_iend_payload_and_trailing_input(self):
        self.rejected("png_chunk_order", png()[:-12] + chunk(b"IEND", b"extra"))
        self.rejected("png_chunk_order", png() + b"trailing secret")
        self.rejected("png_chunk_order", png() + chunk(b"IEND"))

    def test_empty_and_invalid_zlib(self):
        for data in (b"", b"invalid", b"\x00" * 16):
            self.rejected("png_zlib_invalid", png(compressed=data))

    def test_decompressed_too_short(self):
        self.rejected("png_zlib_invalid", png(pixels=b"\0" * 17))

    def test_decompressed_one_byte_too_long(self):
        self.rejected("png_decompression_limit", png(pixels=b"\0" * 19))

    def test_compressed_bomb_is_bounded(self):
        data = zlib.compress(b"\0" * (8 * 1024 * 1024))
        self.assertLess(len(data), files.MAX_PNG_BYTES)
        self.rejected("png_decompression_limit", png(width=1, height=1, compressed=data))

    def test_zlib_read_has_output_limit_and_no_unbounded_flush(self):
        real_factory = zlib.decompressobj
        calls = []

        class GuardedDecoder:
            def __init__(self):
                self.actual = real_factory()

            def decompress(self, data, maximum):
                calls.append(maximum)
                return self.actual.decompress(data, maximum)

            def __getattr__(self, name):
                if name == "flush":
                    raise AssertionError("unbounded flush")
                return getattr(self.actual, name)

        with mock.patch.object(files.zlib, "decompressobj", GuardedDecoder):
            files.sanitize_native_png(png())
        self.assertEqual(calls, [19])

    def test_truncated_zlib_checksum(self):
        data = zlib.compress((b"\0" + b"x" * 8) * 2)
        self.rejected("png_zlib_invalid", png(compressed=data[:-1]))

    def test_concatenated_zlib_and_unused_data(self):
        data = zlib.compress((b"\0" + b"x" * 8) * 2)
        for tail in (b"private", b"\0", zlib.compress(b"hidden")):
            self.rejected("png_zlib_invalid", png(compressed=data + tail))

    def test_bad_zlib_checksum(self):
        data = bytearray(zlib.compress((b"\0" + b"x" * 8) * 2))
        data[-1] ^= 1
        self.rejected("png_zlib_invalid", png(compressed=bytes(data)))

    def test_no_pillow_dependency(self):
        import sys
        with mock.patch.dict(sys.modules, {"PIL": None, "PIL.Image": None}):
            self.assertEqual(files.sanitize_native_png(png()).data, png())


if __name__ == "__main__":
    unittest.main()
