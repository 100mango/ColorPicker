"""Portable adversarial snapshot tests; no Apple reader or external writes."""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import stat
import tempfile
import time
import unittest
from unittest.mock import patch

import vision_result_snapshot as snapshots


class Clock:
    def __init__(self):
        self.value = 1.
    def __call__(self):
        return self.value


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.root = self.base / 'source'
        self.root.mkdir()
        self.bundle = 'build/vision-tests.xcresult'
        self.source = self.root / self.bundle
        (self.source / 'Data/empty').mkdir(parents=True)
        (self.source / 'Empty').mkdir()
        (self.source / 'Info.plist').write_bytes(b'fixture info\x00')
        (self.source / 'Data/result').write_bytes(b'\x00fixture result\xff')
        self.temp = self.base / 'scratch'
        self.temp.mkdir()
        self.temp_patch = patch.object(snapshots.tempfile, 'gettempdir', return_value=str(self.temp))
        self.temp_patch.start()
        self.addCleanup(self.temp_patch.stop)
        self.clock = Clock()
        self.receipt = {}

    def binding(self, **kwargs):
        return snapshots.source_binding(self.root, self.bundle, clock=self.clock, **kwargs)

    def create(self, binding=None, deadline=16.):
        owner = snapshots.create(self.root, self.bundle, binding or self.binding(), self.receipt,
                                 deadline, clock=self.clock)
        self.addCleanup(owner.cleanup)
        return owner

    def test_complete_independent_byte_copy_includes_empty_directories(self):
        original = self.binding()
        owner = self.create(original)
        self.assertEqual(owner.path.resolve(), owner.path)
        self.assertFalse(owner.path.is_relative_to(self.root))
        self.assertEqual(stat.S_IMODE(owner.owned_root.stat().st_mode), 0o700)
        self.assertEqual(len(list(self.temp.iterdir())), 1)
        self.assertEqual(owner.identity['sha256'], original['sha256'])
        self.assertEqual(owner.input_binding['full_tree_sha256'], original['full_tree_sha256'])
        self.assertNotEqual(owner.input_binding['node_identity_sha256'], original['node_identity_sha256'])
        self.assertNotEqual(owner.identity['inode'], original['inode'])
        self.assertTrue((owner.path/'Data/empty').is_dir())
        self.assertTrue((owner.path/'Empty').is_dir())
        for name in ('Info.plist', 'Data/result'):
            self.assertEqual((owner.path/name).read_bytes(), (self.source/name).read_bytes())
            self.assertNotEqual((owner.path/name).stat().st_ino, (self.source/name).stat().st_ino)
            self.assertEqual((owner.path/name).stat().st_nlink, 1)
        self.assertTrue(owner.verify())
        self.assertEqual(owner.verify_input(), owner.input_binding)
        self.assertEqual(owner.verify_original(), original)
        self.assertTrue(owner.cleanup())
        self.assertTrue(owner.cleanup())
        self.assertFalse(owner.owned_root.exists())
        self.assertTrue(self.receipt['snapshot']['cleanup']['confirmed'])
        self.assertTrue(self.receipt['snapshot']['cleanup']['deleted'])
        self.assertEqual(self.binding(), original)
        self.assertLess(len(json.dumps(self.receipt).encode()), 10000)
        with self.assertRaises(ValueError):
            owner.verify()

    def test_legacy_content_digest_matches_existing_walk_order(self):
        (self.source/'a').mkdir()
        (self.source/'a/a').write_bytes(b'A')
        (self.source/'Data/z').write_bytes(b'Z')
        digest = hashlib.sha256()
        for folder, dirs, files in os.walk(self.source):
            dirs.sort()
            for name in sorted(files):
                path = Path(folder)/name
                digest.update(path.relative_to(self.source).as_posix().encode()+b'\0'+str(path.stat().st_size).encode()+b'\0')
                digest.update(path.read_bytes())
                digest.update(b'\0')
        self.assertEqual(self.binding()['sha256'], digest.hexdigest())

    def test_symlink_tmpdir_is_canonicalized_without_adopting_source_aliases(self):
        alias = self.base/'temp-alias'
        alias.symlink_to(self.temp, target_is_directory=True)
        with patch.object(snapshots.tempfile, 'gettempdir', return_value=str(alias)):
            owner = self.create()
        self.assertEqual(owner.owned_root.parent, self.temp)
        source_alias = self.base/'source-alias'
        source_alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            snapshots.source_binding(source_alias, self.bundle, clock=self.clock)

    def test_rejects_symlink_hardlink_and_special_file_before_copy(self):
        for kind in ('symlink-file', 'symlink-dir', 'hardlink', 'fifo'):
            with self.subTest(kind=kind):
                target = self.source/'bad'
                if kind == 'symlink-file': target.symlink_to(self.source/'Info.plist')
                elif kind == 'symlink-dir': target.symlink_to(self.source/'Data', target_is_directory=True)
                elif kind == 'hardlink': os.link(self.source/'Info.plist', target)
                else: os.mkfifo(target)
                try:
                    with self.assertRaises(ValueError): self.binding()
                    self.assertEqual(list(self.temp.iterdir()), [])
                finally:
                    target.unlink()

    def test_rejects_source_bundle_replacement_and_file_identity_replacement(self):
        for which in ('bundle', 'file'):
            with self.subTest(which=which):
                binding = self.binding()
                if which == 'bundle':
                    old = self.source.with_name('old.xcresult')
                    self.source.rename(old)
                    shutil.copytree(old, self.source)
                else:
                    path = self.source/'Info.plist'
                    data = path.read_bytes()
                    old_stat = path.stat()
                    replacement = self.source/'replacement'
                    replacement.write_bytes(data)
                    os.utime(replacement, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns))
                    replacement.replace(path)
                with self.assertRaises(ValueError): self.create(binding)
                self.assertEqual(list(self.temp.iterdir()), [])

    def test_full_tree_guard_detects_empty_directory_rename_even_legacy_matches(self):
        original = self.binding()
        (self.source/'Empty').rename(self.source/'Other')
        changed = self.binding()
        self.assertEqual(original['sha256'], changed['sha256'])
        self.assertEqual(original['directories'], changed['directories'])
        self.assertNotEqual(original['full_tree_sha256'], changed['full_tree_sha256'])
        with self.assertRaises(ValueError): self.create(original)

    def test_reader_can_mutate_private_copy_but_never_source_or_input_proof(self):
        owner = self.create()
        original = self.binding()
        (owner.path/'Info.plist').write_bytes(b'reader mutation')
        self.assertTrue(owner.verify())
        with self.assertRaises(ValueError): owner.verify_input()
        self.assertEqual(owner.verify_original(), original)
        self.assertTrue(owner.cleanup())
        self.assertEqual(self.binding(), original)

    def test_independent_readback_rejects_copy_corruption_and_missing_empty_dir(self):
        actual_copy = snapshots._copy
        for change in ('bytes', 'empty-dir', 'new-file'):
            with self.subTest(change=change):
                def corrupt(source, destination, nodes, deadline, clock):
                    actual_copy(source, destination, nodes, deadline, clock)
                    if change == 'bytes':
                        fd = os.open('Info.plist', os.O_WRONLY|os.O_TRUNC, dir_fd=destination)
                        os.write(fd, b'corrupt')
                        os.close(fd)
                    elif change == 'empty-dir': os.rmdir('Empty', dir_fd=destination)
                    else:
                        fd = os.open('added', os.O_WRONLY|os.O_CREAT, 0o600, dir_fd=destination)
                        os.close(fd)
                with patch.object(snapshots, '_copy', side_effect=corrupt):
                    with self.assertRaises(ValueError): self.create()
                self.assertTrue(self.receipt['snapshot']['cleanup']['confirmed'])
                self.assertEqual(list(self.temp.iterdir()), [])

    def test_source_mutation_during_copy_is_rejected_with_confirmed_cleanup(self):
        actual_copy = snapshots._copy
        def mutate(*args):
            actual_copy(*args)
            (self.source/'Info.plist').write_bytes(b'changed original')
        with patch.object(snapshots, '_copy', side_effect=mutate):
            with self.assertRaises(ValueError): self.create()
        self.assertTrue(self.receipt['snapshot']['cleanup']['confirmed'])
        self.assertEqual(list(self.temp.iterdir()), [])

    def test_source_mutation_after_creation_fails_original_guard(self):
        owner = self.create()
        (self.source/'Info.plist').write_bytes(b'changed')
        with self.assertRaises(ValueError): owner.verify_original()
        self.assertTrue(owner.cleanup())

    def test_cleanup_unlinks_reader_added_links_without_following_them(self):
        owner = self.create()
        outside = self.base/'untouched'
        outside.mkdir()
        sentinel = outside/'sentinel'
        sentinel.write_bytes(b'keep')
        (owner.path/'escape').symlink_to(outside, target_is_directory=True)
        os.link(sentinel, owner.path/'linked')
        os.mkfifo(owner.path/'fifo')
        (owner.path/'reader-dir/sub').mkdir(parents=True)
        (owner.path/'reader-dir/sub/file').write_bytes(b'new')
        self.assertTrue(owner.cleanup())
        self.assertEqual(sentinel.read_bytes(), b'keep')
        self.assertEqual(list(outside.iterdir()), [sentinel])
        self.assertEqual(sentinel.stat().st_nlink, 1)

    def test_reader_added_escape_nodes_are_rejected_before_the_next_reader(self):
        for kind in ('symlink', 'hardlink', 'fifo'):
            with self.subTest(kind=kind):
                owner = self.create()
                target = owner.path/'reader-node'
                if kind == 'symlink': target.symlink_to(self.source, target_is_directory=True)
                elif kind == 'hardlink': os.link(self.source/'Info.plist', target)
                else: os.mkfifo(target)
                with self.assertRaises(ValueError): owner.verify()
                self.assertTrue(owner.cleanup())

    def test_reader_additions_are_metadata_checked_without_rejecting_safe_mutation(self):
        owner = self.create()
        (owner.path/'extra').mkdir()
        (owner.path/'extra/file').write_bytes(b'private reader state')
        self.assertTrue(owner.verify())
        self.assertEqual(self.receipt['snapshot']['reader_input_guard']['files'], 3)
        with patch.object(snapshots, 'MAX_FILES', 2):
            with self.assertRaises(ValueError): owner.verify()
        self.assertTrue(owner.cleanup())

    def test_cleanup_interruption_is_unconfirmed_and_bounded(self):
        owner = self.create()
        with patch.object(snapshots, '_names', side_effect=KeyboardInterrupt):
            self.assertFalse(owner.cleanup())
        self.assertFalse(self.receipt['snapshot']['cleanup']['confirmed'])
        self.assertTrue(owner.owned_root.exists())

    def test_foreign_replacement_root_is_never_deleted(self):
        owner = self.create()
        old = owner.owned_root.with_name('moved-owned-root')
        owner.owned_root.rename(old)
        owner.owned_root.mkdir(mode=0o700)
        (owner.owned_root/'foreign').write_bytes(b'keep')
        with self.assertRaises(ValueError): owner.verify()
        self.assertFalse(owner.cleanup())
        self.assertEqual((owner.owned_root/'foreign').read_bytes(), b'keep')
        self.assertTrue((old/self.source.name/'Info.plist').exists())
        self.assertFalse(self.receipt['snapshot']['cleanup']['confirmed'])

    def test_snapshot_bundle_replaced_is_not_an_accepted_reader_input(self):
        owner = self.create()
        old = owner.path.with_name('moved.xcresult')
        owner.path.rename(old)
        shutil.copytree(old, owner.path)
        with self.assertRaises(ValueError): owner.verify()
        self.assertTrue(owner.cleanup())

    def test_stale_root_name_collision_never_adopts_or_deletes_existing_data(self):
        class Fixed:
            hex = 'a'*32
        old = self.temp/('touchcolor-vision-result-'+Fixed.hex)
        old.mkdir(mode=0o700)
        sentinel = old/'keep'
        sentinel.write_bytes(b'old')
        with patch.object(snapshots.uuid, 'uuid4', return_value=Fixed()):
            with self.assertRaises(FileExistsError): self.create()
        self.assertEqual(sentinel.read_bytes(), b'old')
        self.assertTrue(self.receipt['snapshot']['cleanup']['not_created'])

    def test_ambiguous_post_mkdir_exception_never_claims_confirmed_cleanup(self):
        real=snapshots.os.mkdir
        def interrupted(name,*args,**kwargs):
            real(name,*args,**kwargs)
            if str(name).startswith('touchcolor-vision-result-'):
                raise KeyboardInterrupt('synthetic interruption after syscall')
        with patch.object(snapshots.os,'mkdir',side_effect=interrupted):
            with self.assertRaises(KeyboardInterrupt):self.create()
        cleanup=self.receipt['snapshot']['cleanup']
        self.assertFalse(cleanup['confirmed']);self.assertFalse(cleanup['not_created'])
        self.assertFalse(cleanup['deleted']);self.assertEqual(len(list(self.temp.iterdir())),1)

    def test_real_cancellation_after_mkdir_waits_for_owned_anchor_then_cleans(self):
        real=snapshots.os.mkdir
        def cancelled(name,*args,**kwargs):
            real(name,*args,**kwargs)
            if str(name).startswith('touchcolor-vision-result-'):signal.raise_signal(signal.SIGTERM)
        def stop(signum,frame):raise KeyboardInterrupt('real pending signal')
        previous=signal.signal(signal.SIGTERM,stop)
        try:
            with patch.object(snapshots.os,'mkdir',side_effect=cancelled):
                with self.assertRaises(KeyboardInterrupt):self.create()
        finally:signal.signal(signal.SIGTERM,previous)
        self.assertTrue(self.receipt['snapshot']['cleanup']['confirmed'])
        self.assertTrue(self.receipt['snapshot']['cleanup']['deleted'])
        self.assertEqual(list(self.temp.iterdir()),[])

    def test_deadline_applies_to_copy_and_independent_verification_together(self):
        actual_copy = snapshots._copy
        def slow(*args):
            actual_copy(*args)
            self.clock.value = 16.
        with patch.object(snapshots, '_copy', side_effect=slow):
            with self.assertRaisesRegex(ValueError, 'deadline'): self.create()
        self.assertTrue(self.receipt['snapshot']['cleanup']['confirmed'])
        self.assertEqual(self.receipt['snapshot']['deadline'], 16.)
        self.assertLessEqual(self.receipt['snapshot']['cleanup']['deadline'], 21.)
        self.assertEqual(list(self.temp.iterdir()), [])

    def test_supplied_deadline_cannot_expand_fifteen_second_cap(self):
        owner = self.create(deadline=999.)
        self.assertEqual(self.receipt['snapshot']['deadline'], 16.)
        self.assertTrue(owner.cleanup(deadline=999.))
        self.assertEqual(self.receipt['snapshot']['cleanup']['deadline'], 6.)

    def test_expired_and_nonfinite_deadlines_fail_without_new_roots(self):
        for deadline in (1., 0., float('nan'), float('inf'), True):
            with self.subTest(deadline=deadline):
                with self.assertRaises(ValueError): self.create(deadline=deadline)
                self.assertEqual(list(self.temp.iterdir()), [])

    def test_cleanup_deadline_failure_is_explicit_and_does_not_claim_deletion(self):
        owner = self.create()
        self.assertFalse(owner.cleanup(deadline=self.clock()))
        self.assertTrue(owner.owned_root.exists())
        self.assertFalse(self.receipt['snapshot']['cleanup']['confirmed'])
        self.assertFalse(self.receipt['snapshot']['cleanup']['deleted'])

    def test_file_directory_and_byte_caps_and_bounded_partial_inventory(self):
        for limit, value in (('MAX_FILES', 1), ('MAX_DIRECTORIES', 2), ('MAX_BYTES', 1)):
            with self.subTest(limit=limit), patch.object(snapshots, limit, value):
                inventory = {}
                with self.assertRaises(ValueError): self.binding(inventory=inventory)
                self.assertFalse(inventory['walk_complete'])
                self.assertLess(len(json.dumps(inventory)), 4096)
        for index in range(260): (self.source/('file-%03d'%index)).write_bytes(b'x')
        inventory = {}
        self.binding(inventory=inventory)
        self.assertEqual(len(inventory['records']), 256)
        self.assertEqual(inventory['omitted_files'], 6)
        self.assertEqual(inventory['observed_files'], 262)

    def test_no_filename_exception_for_reader_generated_metadata(self):
        for name in ('.DS_Store', 'manifest.json', 'metadata.json'):
            owner = self.create()
            (owner.path/name).write_bytes(b'new')
            with self.assertRaises(ValueError): owner.verify_input()
            self.assertTrue(owner.cleanup())

    def test_source_temp_location_inside_evidence_is_rejected(self):
        with patch.object(snapshots.tempfile, 'gettempdir', return_value=str(self.root/'build')):
            with self.assertRaisesRegex(ValueError, 'source/evidence'): self.create()
        self.assertEqual(list(self.temp.iterdir()), [])

    def test_nested_replacement_after_observation_is_detected(self):
        original_read = snapshots.os.read
        changed = [False]
        def read(fd, size):
            chunk = original_read(fd, size)
            if chunk == b'\x00fixture result\xff' and not changed[0]:
                changed[0] = True
                (self.source/'Info.plist').write_bytes(b'subsequent mutation')
            return chunk
        with patch.object(snapshots.os, 'read', side_effect=read):
            with self.assertRaises(ValueError): self.binding()

    def test_copy_write_failure_cleans_partial_output(self):
        with patch.object(snapshots.os, 'write', side_effect=OSError('full device')):
            with self.assertRaises(OSError): self.create()
        self.assertTrue(self.receipt['snapshot']['cleanup']['confirmed'])
        self.assertEqual(list(self.temp.iterdir()), [])

    def test_short_writes_are_completed_as_ordinary_byte_copies(self):
        original_write = snapshots.os.write
        def short(fd, data):
            return original_write(fd, data[:1])
        with patch.object(snapshots.os, 'write', side_effect=short):
            owner = self.create()
        self.assertEqual(owner.verify_input(), owner.input_binding)
        self.assertTrue(owner.cleanup())

    def test_source_relative_path_aliases_are_rejected(self):
        for bundle in ('build/../build/vision-tests.xcresult', './'+self.bundle,
                       '/'+self.bundle, 'build//vision-tests.xcresult'):
            with self.subTest(bundle=bundle):
                with self.assertRaises(ValueError): snapshots.source_binding(self.root, bundle, clock=self.clock)

    def test_interruption_during_copy_cleans_owned_root_before_propagating(self):
        with patch.object(snapshots, '_copy', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt): self.create()
        self.assertTrue(self.receipt['snapshot']['cleanup']['confirmed'])
        self.assertEqual(list(self.temp.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
