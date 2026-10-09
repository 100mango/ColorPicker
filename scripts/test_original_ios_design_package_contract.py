"""Exact corrected source graph and localized policy contracts; no native tools."""
from pathlib import Path
import hashlib, unittest
import verify_original_ios_package as package
import test_original_ios_package as fixtures

class CorrectedDesignContractTests(unittest.TestCase):
    def fixture(self):
        owner = fixtures.PackageTests(); self.addCleanup(owner.doCleanups)
        return owner.fixture()
    def test_exact_thirteen_members_keep_all_previous_sources(self):
        previous = {'ColorPicker/' + name for name in ['main.m','ColorAppDelegate.m','ColorSceneDelegate.m','ColorMainViewController.m',
                    'ColorViewController.m','ColorRealTimeViewController.m','ColorDetectView.m','TCColorUtilities.m',
                    'TCPrivacyViewController.m','TCWorkspaceViewController.m','TCPhotoImportTask.swift']}
        previous.add('TouchColorPhoneCompanion/PhonePaletteImportController.swift')
        observed = package.source_graph(package.ROOT)
        self.assertEqual(set(observed['source_paths']), previous | {'ColorPicker/TCOriginalDesign.m'})
        self.assertEqual(len(observed['source_paths']), 13)
    def test_missing_extra_duplicate_or_redirected_member_rejects(self):
        for change in ['missing','extra','duplicate','redirect']:
            with self.subTest(change=change):
                f = self.fixture(); objects = f.project['objects']; files=objects['sources']['files']
                if change == 'missing': files.pop()
                elif change == 'duplicate': files.append(files[0])
                elif change == 'extra':
                    objects['foreign-build']={'isa':'PBXBuildFile','fileRef':'foreign-ref'}
                    objects['foreign-ref']={'isa':'PBXFileReference','path':'ColorPicker/Unreviewed.m'};files.append('foreign-build')
                else: objects[objects[files[0]]['fileRef']]['path']='ColorPicker/Unreviewed.m'
                f.write_project()
                with self.assertRaisesRegex(ValueError,'source membership'): package.source_graph(f.root)
    def test_original_design_source_missing_tampered_or_linked_rejects(self):
        for name in package.ORIGINAL_DESIGN_SOURCES:
            for change in ['missing','tampered','linked']:
                with self.subTest(name=name,change=change):
                    f=self.fixture();p=f.root/name
                    if change=='missing':p.unlink()
                    elif change=='tampered':p.write_bytes(p.read_bytes()+b'\n// changed\n')
                    else:p.unlink();p.symlink_to(package.ROOT/name)
                    with self.assertRaises(ValueError):package.source_graph(f.root)
    def test_each_approved_locale_hash_rejects_any_file_tamper(self):
        for language,digest in package.POLICY_LOCALIZATIONS.items():
            f=self.fixture();p=f.root/f'ColorPicker/{language}.lproj/Localizable.strings'
            self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(),digest)
            p.write_bytes(p.read_bytes()+b'\n"Unexpected" = "Change";\n')
            with self.assertRaisesRegex(ValueError,'localization changed'):package.source_graph(f.root)

if __name__=='__main__':unittest.main()
