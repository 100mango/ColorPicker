"""Portable projection/source contracts; these are not a phone/Watch UI pass."""
from pathlib import Path
import copy, hashlib, json, subprocess, sys, tempfile, unittest
import xml.etree.ElementTree as ET
import generate_ios_watch_project as g
import verify_original_ios_package as old

ROOT=Path(__file__).resolve().parents[1]


def validate(root=ROOT):
    expected=g.projection(root)
    actual=old.generated_project((root/g.PROJECT/'project.pbxproj').read_bytes())
    g.need(actual==expected,'fixed iOS Watch project graph mismatch')
    for path,text in g.projected_sources(root).items():
        g.need((root/path).read_text()==text,'fixed integration projection mismatch: '+path)
    # Original isolated graph still excludes Watch and retains latest importer.
    original=old.source_graph(root)
    objects=actual['objects'];app=objects[g.uid('TouchColor')]
    phases=[objects[p] for p in app['buildPhases']]
    sources=[objects[objects[b]['fileRef']]['path'] for phase in phases if phase['isa']=='PBXSourcesBuildPhase' for b in phase['files']]
    g.need(len(sources)==len(set(sources)),'duplicate app source')
    g.need(sources.count('TouchColorPhoneCompanion/PhonePaletteInbox.swift')==1 and sources.count('TouchColorPhoneCompanion/PhonePaletteInboxController.swift')==1 and sources.count('TouchColorPhoneCompanion/PhonePaletteImportController.swift')==1,'actual inbox/import membership')
    embeds=[p for p in phases if p['isa']=='PBXCopyFilesBuildPhase']
    g.need(len(embeds)==1 and embeds[0]['dstPath']=='$(CONTENTS_FOLDER_PATH)/Watch' and embeds[0]['dstSubfolderSpec']==16 and len(embeds[0]['files'])==1,'fixed Watch embed')
    watch=old.generated_project((root/'TouchColorWatch.xcodeproj/project.pbxproj').read_bytes())['objects']
    dependency=objects[app['dependencies'][0]];proxy=objects[dependency['targetProxy']]
    target=watch[proxy['remoteGlobalIDString']]
    g.need(target['name']=='TouchColorWatch' and watch[target['productReference']]['path']=='TouchColor.app','real external Watch target')
    product=objects[objects[embeds[0]['files'][0]]['fileRef']]
    remote=objects[product['remoteRef']]
    g.need(remote['remoteGlobalIDString']==target['productReference'] and product['path']=='TouchColor.app','real external Watch product')
    for config in watch[target['buildConfigurationList']]['buildConfigurations']:
        settings=watch[config]['buildSettings']
        g.need(settings['INFOPLIST_KEY_WKCompanionAppBundleIdentifier']=='com.mango.touchColor' and settings['INFOPLIST_KEY_WKRunsIndependentlyOfCompanionApp']=='YES','Watch companion mode')
        g.need(settings['WATCHOS_DEPLOYMENT_TARGET']=='9.0' and settings['MARKETING_VERSION']=='2.0' and settings['CURRENT_PROJECT_VERSION']=='20001','Watch version/floor')
    scheme=ET.parse(root/g.PROJECT/'xcshareddata/xcschemes/TouchColor.xcscheme')
    archiving=scheme.findall("./BuildAction/BuildActionEntries/BuildActionEntry[@buildForArchiving='YES']")
    g.need(len(archiving)==1 and archiving[0].find('BuildableReference').get('BlueprintName')=='TouchColor','sole parent scheme archive')
    g.need(all(x.get('ReferencedContainer')=='container:'+g.PROJECT for x in scheme.iter('BuildableReference')),'scheme project binding')
    return {'original':original,'sources':sources,'project_sha256':hashlib.sha256((root/g.PROJECT/'project.pbxproj').read_bytes()).hexdigest()}


class ProjectTests(unittest.TestCase):
    def test_real_projection_preserves_original_and_membership(self):
        result=validate();self.assertEqual(len(result['sources']),14)
        self.assertFalse(any('Inbox' in p for p in result['original']['source_paths']))
    def test_generation_is_idempotent_without_original_mutation(self):
        paths=[ROOT/g.PROJECT/'project.pbxproj',ROOT/g.PROJECT/'xcshareddata/xcschemes/TouchColor.xcscheme',*[ROOT/p for p in g.projected_sources()],ROOT/'TouchColor.xcodeproj/project.pbxproj',ROOT/'TouchColorWatch.xcodeproj/project.pbxproj']
        before={str(p):p.read_bytes() for p in paths};g.generate()
        self.assertEqual(before,{str(p):p.read_bytes() for p in paths})
    def test_projection_retains_unrelated_current_source_bytes(self):
        for name,operations in g.OPERATIONS.items():
            value=g.projected_sources()[g.INTEGRATION+'/'+name]
            for old_value,new_value,count in reversed(operations):
                self.assertEqual(value.count(new_value),count)
                value=value.replace(new_value,old_value)
            self.assertEqual(value,(ROOT/'ColorPicker'/name).read_text())
    def test_only_existing_inbox_core_is_reenabled(self):
        inbox=(ROOT/'TouchColorPhoneCompanion/PhonePaletteInbox.swift').read_text()
        for token in ('PaletteTransfer.maximumBytes','receiptRoutes.isCurrent(epoch)','receiptRoutes.admit(request.id','try inbox.accept(id)','try inbox.reject(id)','transfer.cancel()'):
            self.assertIn(token,inbox)
        self.assertNotIn('PHPhotoLibrary',inbox)
        self.assertEqual(g.projected_sources()[g.INTEGRATION+'/ColorAppDelegate.m'].count('[[TCWatchPaletteInbox sharedInbox] activate];'),1)
    def test_shared_import_and_photo_lifecycle_are_not_replaced(self):
        result=validate()
        for source in ('ColorPicker/TCPhotoImportTask.swift','ColorPicker/ColorSceneDelegate.m','TouchColorPhoneCompanion/PhonePaletteImportController.swift'):
            self.assertIn(source,result['sources'])
        self.assertEqual(hashlib.sha256((ROOT/'TouchColorPhoneCompanion/PhonePaletteImportController.swift').read_bytes()).hexdigest(),old.IMPORT_SHA)
    def test_old_original_route_still_rejects_watch(self):
        self.assertEqual(old.source_graph(ROOT)['importer_sha256'],old.IMPORT_SHA)
        # The unmodified old package suite supplies actual negative Watch cases.
        original=(ROOT/'scripts/verify_original_ios_package.py').read_text()
        self.assertIn('Watch',original)
        self.assertNotEqual(g.PROJECT,'TouchColor.xcodeproj')
    def test_graph_negative_external_edge_extra_source_and_copy_destination(self):
        # Equality to deterministic frozen projection closes extra edges, source
        # membership, duplicate embed and changed remote product identity.
        expected=g.projection();objects=expected['objects'];app=objects[g.uid('TouchColor')]
        mutations=[]
        for key,value in (('remoteGlobalIDString','F'*24),('containerPortal','E'*24)):
            wrong=copy.deepcopy(expected);wrong['objects'][g.uid('WatchTargetProxy')][key]=value;mutations.append(wrong)
        wrong=copy.deepcopy(expected);wrong['objects'][g.uid('EmbedWatchContent')]['dstPath']='Elsewhere';mutations.append(wrong)
        wrong=copy.deepcopy(expected);wrong['objects'][g.uid('TouchColor')]['dependencies'].append('hidden-harness');mutations.append(wrong)
        wrong=copy.deepcopy(expected);wrong['objects'][g.uid('TouchColorsources')]['files'].append('foreign-source');mutations.append(wrong)
        for wrong in mutations:
            with self.assertRaises(ValueError):g.need(wrong==expected,'fixed iOS Watch project graph mismatch')
    def test_fixed_symbol_names_do_not_collide(self):
        p=g.projection();o=p['objects'];app=o[g.uid('TouchColor')]
        for config in o[app['buildConfigurationList']]['buildConfigurations']:
            self.assertEqual(o[config]['buildSettings']['DWARF_DSYM_FILE_NAME'],'TouchColor-iOS.app.dSYM')

if __name__=='__main__':unittest.main()
