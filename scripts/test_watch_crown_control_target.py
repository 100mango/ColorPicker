"""Independent project/source contracts and actual portable C geometry execution.

These checks do not compile Swift, execute XCTest, or establish native Watch proof.
"""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET

from generate_watch_crown_control_project import APP, UI, generate

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / UI / 'WatchStaticCrownControlTests.swift'
HEADER = ROOT / UI / 'TCStaticListGeometry.h'


class StaticCrownProjectTests(unittest.TestCase):
    def test_generated_project_is_deterministic_and_has_only_isolated_targets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            objects = generate(root)
            first = (root / (APP + '.xcodeproj/project.pbxproj')).read_bytes()
            generate(root)
            self.assertEqual(first, (root / (APP + '.xcodeproj/project.pbxproj')).read_bytes())
            self.assertEqual(first, (ROOT / (APP + '.xcodeproj/project.pbxproj')).read_bytes())
        targets = {item['name']: item for item in objects.values() if item['isa'] == 'PBXNativeTarget'}
        self.assertEqual(set(targets), {APP, UI})
        self.assertEqual(targets[APP]['dependencies'], [])
        dependency = objects[targets[UI]['dependencies'][0]]
        self.assertEqual(objects[dependency['target']]['name'], APP)
        self.assertFalse(any('Package' in item['isa'] for item in objects.values()))
        compiled = []
        for target in targets.values():
            for phase_id in target['buildPhases']:
                phase = objects[phase_id]
                if phase['isa'] == 'PBXSourcesBuildPhase':
                    compiled.extend(objects[objects[f]['fileRef']]['path'] for f in phase['files'])
                elif phase['isa'] in ('PBXFrameworksBuildPhase', 'PBXResourcesBuildPhase'):
                    self.assertEqual(phase['files'], [])
        self.assertEqual(compiled, [APP + '/StaticCrownControlApp.swift', UI + '/WatchStaticCrownControlTests.swift'])
        for item in objects.values():
            if item['isa'] == 'PBXFileReference' and item['sourceTree'] == '<group>':
                self.assertTrue(item['path'].startswith((APP + '/', UI + '/')))

    def test_debug_only_scheme_configs_and_compile_guards(self):
        with tempfile.TemporaryDirectory() as directory:
            objects = generate(Path(directory))
            scheme_path = Path(directory) / (APP + '.xcodeproj/xcshareddata/xcschemes/' + APP + '.xcscheme')
            self.assertEqual(scheme_path.read_bytes(), (ROOT / scheme_path.relative_to(directory)).read_bytes())
            scheme = ET.parse(scheme_path).getroot()
        configs = [item for item in objects.values() if item['isa'] == 'XCBuildConfiguration']
        self.assertEqual(len(configs), 3)
        self.assertTrue(all(c['name'] == 'Debug' for c in configs))
        self.assertTrue(all(c['buildSettings']['SWIFT_ACTIVE_COMPILATION_CONDITIONS'] == 'DEBUG' for c in configs))
        self.assertIsNone(scheme.find('ArchiveAction'))
        self.assertEqual(scheme.find('TestAction').get('buildConfiguration'), 'Debug')
        testables = scheme.findall('TestAction/Testables/TestableReference')
        self.assertEqual(len(testables), 1)
        self.assertEqual(testables[0].get('parallelizable'), 'NO')
        self.assertEqual(testables[0].find('BuildableReference').get('BlueprintName'), UI)
        self.assertTrue(all(e.get('buildForArchiving') == 'NO' for e in scheme.findall('BuildAction/BuildActionEntries/BuildActionEntry')))
        for path in [ROOT / APP / 'StaticCrownControlApp.swift', SOURCE]:
            source = path.read_text()
            self.assertTrue(source.startswith('#if DEBUG\n'))
            self.assertIn('#else\n#error(', source)
        app_config = next(c for c in configs if c['buildSettings'].get('PRODUCT_MODULE_NAME') == APP)
        self.assertEqual(app_config['buildSettings']['PRODUCT_BUNDLE_IDENTIFIER'], 'com.mango.touchColor.watchCrownControl')
        self.assertNotIn('INFOPLIST_KEY_WKCompanionAppBundleIdentifier', app_config['buildSettings'])

    def test_standalone_watch_only_packaging_omits_companion_independence_key(self):
        # Apple WKWatchOnly is the topology for this standalone app. The failed
        # 932adf install treated presence of both keys as ambiguous. Require
        # absence of the companion key, rather than substituting a false value.
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);objects=generate(root)
            project=(root/(APP+'.xcodeproj/project.pbxproj')).read_text()
        configs=[v['buildSettings'] for v in objects.values() if v['isa']=='XCBuildConfiguration']
        app_settings=[v for v in configs if v.get('PRODUCT_MODULE_NAME')==APP]
        self.assertEqual(len(app_settings),1)
        self.assertEqual(app_settings[0]['INFOPLIST_KEY_WKWatchOnly'],'YES')
        self.assertEqual(app_settings[0]['INFOPLIST_KEY_WKApplication'],'YES')
        for settings in configs:
            self.assertNotIn('INFOPLIST_KEY_WKRunsIndependentlyOfCompanionApp',settings)
            self.assertNotIn('INFOPLIST_KEY_WKCompanionAppBundleIdentifier',settings)
        self.assertNotIn('WKRunsIndependentlyOfCompanionApp',project)
        self.assertNotIn('WKCompanionAppBundleIdentifier',project)
        self.assertNotIn('WKRunsIndependentlyOfCompanionApp',(ROOT/'scripts/generate_watch_crown_control_project.py').read_text())

    def test_static_application_has_no_product_state_focus_or_crown_handler(self):
        source = (ROOT / APP / 'StaticCrownControlApp.swift').read_text()
        self.assertEqual(re.findall(r'^import (\w+)$', source, re.M), ['SwiftUI'])
        for expected in ('NavigationStack {', 'List {', 'ForEach(0..<12, id: \\.self)',
                         'NavigationLink(destination: Text("Static destination"))', 'static.row.\\(index)'):
            self.assertIn(expected, source)
        for forbidden in ('@State', '@ObservedObject', '@StateObject', '@EnvironmentObject', 'UserDefaults',
                          'WatchConnectivity', 'ColorDomain', 'digitalCrownRotation', '.focus', '.prefersDefaultFocus',
                          '.task', '.onAppear', '.onChange', '.onReceive', 'Palette', 'Transfer'):
            self.assertNotIn(forbidden, source)

    def test_exact_rotation_and_independent_strict_status_contract(self):
        source = SOURCE.read_text()
        method = source.split('@MainActor func testStaticListDigitalCrownThreeRotations()', 1)[1]
        self.assertEqual(len(re.findall(r'func test\w+\(', source)), 1)
        self.assertIn('for attempt in 0..<3', method)
        self.assertEqual(source.count('rotateDigitalCrown('), 1)
        self.assertIn('XCUIDevice.shared.rotateDigitalCrown(delta: -0.1)', method)
        self.assertNotIn('break }', method)
        self.assertIn('try validateTop(before)', method)
        self.assertIn('b.minY < a.minY - 1', source)
        movement = source.split('private func movement(', 1)[1].split('@MainActor private func capture(', 1)[0]
        self.assertIn('same(before.navigation, after.navigation) else', movement)
        self.assertIn('return .downward', movement)
        self.assertLess(movement.index('same(before.navigation, after.navigation) else'), movement.index('return .downward'))
        for expected in ('listIdentityMatches && navigationIdentityMatches', 'backButtons == 0',
                         '"listIdentifier": listIdentifier', '"navigationTitle": navigationTitle',
                         '"backButtons": backButtons', 'element.identifier == "BackButton"'):
            self.assertIn(expected, source)
        self.assertIn('frame.rows[11].map({ !$0.intersects(frame.viewport) }) ?? true', source)
        self.assertIn('first.minY - CGFloat(content.y) <= 12', source)
        self.assertIn('"com.mango.touchColor.watchkitapp").state == .notRunning', method)
        self.assertIn('if crownStatus == "stationary", let last { try touchControl(after: last) }', method)
        self.assertLess(method.index('} catch {'), method.index('try emitResult()'))
        self.assertLess(method.index('try emitResult()'), method.index('XCTAssertEqual(crownStatus, "moved_downward"'))
        touch = source.split('private func touchControl(', 1)[1].split('private func emitResult()', 1)[0]
        self.assertNotIn('crownStatus =', touch)
        self.assertEqual(touch.count('start.press('), 1)
        for forbidden in ('swipeUp(', 'swipeDown(', 'XCTSkip', 'XCTExpectFailure', 'debugDescription', '.tap()'):
            self.assertNotIn(forbidden, source)

    def test_snapshot_traversal_rows_and_total_bytes_are_bounded(self):
        source = SOURCE.read_text()
        self.assertEqual(source.count('app.snapshot()'), 1)
        for expected in ('guard crownSnapshots < 6 else', 'guard touchSnapshots < 2 else', 'visited < Self.maxNodes',
                         'Self.maxNodes - visited - pending.count', 'children.prefix(retained)',
                         'rows.count >= Self.maxRows', 'pruned += children.count - retained',
                         'pruned += pending.count', '"omittedDescendantsUnknown": pruned > 0',
                         '"omittedRows":', '"omittedFrames":', '"snapshotErrors":',
                         'candidate.count <= Self.maxFrameBytes', 'printedRows.removeLast()',
                         'frame.complete && byteDrops == 0', 'Self.maxStructuredBytes - Self.maxSummaryBytes'):
            self.assertIn(expected, source)
        node_limit = int(re.search(r'maxNodes = (\d+)', source)[1])
        row_limit = int(re.search(r'maxRows = (\d+)', source)[1])
        frame_limit = int(re.search(r'maxFrameBytes = (\d+)', source)[1])
        summary_limit = int(re.search(r'maxSummaryBytes = (\d+)', source)[1])
        self.assertEqual((node_limit, row_limit), (256, 12))
        self.assertLessEqual(8 * frame_limit + summary_limit + 9 * 32, 16 * 1024)
        self.assertIn('private static let maxStructuredBytes = 16 * 1024', source)
        self.assertIn('"touchCanSatisfyCrown": false', source)

    def test_live_touch_geometry_and_fail_closed_interruption(self):
        source = SOURCE.read_text()
        touch = source.split('private func touchControl(', 1)[1].split('private func emitResult()', 1)[0]
        for expected in ('capture("touch.before", touch: true)', 'capture("touch.after", touch: true)',
                         'movement(finalCrown, before) == .stationary', 'TCStaticPlan(',
                         'app.state == .runningForeground', 'lists.count == 1', 'bars.count == 1',
                         'app.frame == before.viewport', 'list.frame == before.list', 'bar.frame == before.navigation',
                         'list.isHittable', 'start.screenPoint ==', 'end.screenPoint ==',
                         'thenHoldForDuration: 0.15'):
            self.assertIn(expected, touch)
        self.assertEqual(touch.count('capture('), 2)
        self.assertGreaterEqual(touch.count('list.frame == before.list'), 2)
        interruption = source.split('addUIInterruptionMonitor(', 1)[1].split('app = XCUIApplication', 1)[0]
        self.assertIn('fatalError(', interruption)
        for forbidden in ('.tap(', 'return false', 'XCTFail(', '.buttons'):
            # Comments are irrelevant to handler behavior.
            active = '\n'.join(line for line in interruption.splitlines() if not line.strip().startswith('//'))
            self.assertNotIn(forbidden, active)


class StaticCrownGeometryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compiler = shutil.which('cc')
        if not cls.compiler:
            raise RuntimeError('C compiler required to execute the actual isolated planner')

    def execute(self, body):
        with tempfile.TemporaryDirectory(prefix='static-crown-geometry-') as directory:
            source, binary = Path(directory) / 'test.c', Path(directory) / 'test'
            source.write_text('#include "' + str(HEADER) + '"\n#include <assert.h>\nint main(void) {\n' + body + '\nreturn 0; }\n')
            result = subprocess.run([self.compiler, '-std=c11', '-Wall', '-Wextra', '-Werror', '-fsanitize=undefined',
                                     str(source), '-lm', '-o', str(binary)], capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_both_retained_profile_sizes_current_navigation_clipping(self):
        self.execute('''
for (int small=0; small<2; small++) {
 double w=small?162:211,h=small?197:257,n=small?47.5:66;
 TCStaticRect v={0,0,w,h},nav={0,0,w,n}; TCStaticDrag p;
 assert(TCStaticPlan(v,v,nav,&p)); assert(p.content.y==n && p.content.height==h-n);
 assert(p.start.x==w/2 && p.end.x==w/2);
 assert(p.start.y>p.end.y && p.start.y-p.end.y<=32);
 assert(p.end.y>n+8 && p.start.y<h-8);
}
''')

    def test_shifted_and_clipped_geometry_is_not_hardcoded(self):
        self.execute('''
TCStaticRect v={10,20,211,257},list={-5,10,240,250},nav={0,15,240,60}; TCStaticDrag p;
assert(TCStaticPlan(v,list,nav,&p));
assert(p.content.x==10 && p.content.y==75 && p.content.width==211 && p.content.height==185);
nav.height=80; assert(TCStaticPlan(v,list,nav,&p)); assert(p.content.y==95 && p.content.height==165);
list=(TCStaticRect){10,110,211,167}; assert(TCStaticPlan(v,list,nav,&p)); assert(p.content.y==110);
list.y=400; assert(!TCStaticPlan(v,list,nav,&p));
''')

    def test_nonfinite_empty_tiny_and_ambiguous_navigation_fail_closed(self):
        self.execute('''
TCStaticRect v={0,0,211,257},nav={0,0,211,66}; TCStaticDrag p;
TCStaticRect bad[]={{NAN,0,211,257},{0,INFINITY,211,257},{0,0,0,257},{0,0,211,-1},{1e308,0,1e308,257}};
for(size_t i=0;i<sizeof(bad)/sizeof(*bad);i++) {
 assert(!TCStaticPlan(bad[i],v,nav,&p)); assert(!TCStaticPlan(v,bad[i],nav,&p)); assert(!TCStaticPlan(v,v,bad[i],&p));
}
assert(!TCStaticPlan(v,v,(TCStaticRect){0,0,211,250},&p));
assert(!TCStaticPlan(v,v,(TCStaticRect){40,0,100,66},&p));
assert(!TCStaticPlan(v,v,(TCStaticRect){0,80,211,66},&p));
assert(!TCStaticPlan(v,v,(TCStaticRect){0,-100,211,20},&p));
assert(!TCStaticPlan(v,v,nav,NULL));
''')

    def test_all_admitted_sizes_keep_single_upward_drag_inside_current_content(self):
        self.execute('''
for(int w=40;w<300;w+=7) for(int h=100;h<350;h+=11) for(int n=10;n<h-60;n+=13) {
 TCStaticRect v={13,17,w,h},nav={13,17,w,n}; TCStaticDrag p;
 assert(TCStaticPlan(v,v,nav,&p));
 assert(p.start.x>v.x+8 && p.end.x<v.x+v.width-8);
 assert(p.end.y>17+n+8 && p.start.y<17+h-8);
 assert(p.start.y>p.end.y && p.start.y-p.end.y<=32.00000001);
}
''')

    def test_top_containment_rejects_partial_or_invalid_rows(self):
        self.execute('''
TCStaticRect content={0,66,211,191};
assert(TCStaticContains(content,(TCStaticRect){2,66,207,59}));
assert(!TCStaticContains(content,(TCStaticRect){2,65,207,59}));
assert(!TCStaticContains(content,(TCStaticRect){2,230,207,59}));
assert(!TCStaticContains(content,(TCStaticRect){2,NAN,207,59}));
''')


if __name__ == '__main__':
    unittest.main()
