"""Execute the actual test-only C planner; this is not native Watch/XCTest proof."""
from pathlib import Path
import json
import shutil
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HEADER = ROOT / 'TouchColorWatchUITests/TCWatchListDragGeometry.h'


class WatchTouchDragTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compiler = shutil.which('cc')
        if not cls.compiler:
            raise RuntimeError('C compiler required; actual planner execution may not be skipped')

    def execute(self, body):
        with tempfile.TemporaryDirectory(prefix='watch-list-drag-') as directory:
            source, binary = Path(directory) / 'test.c', Path(directory) / 'test'
            source.write_text('#include "' + str(HEADER) + '"\n#include <assert.h>\nint main(void){\n' + body + '\nreturn 0;}\n')
            result = subprocess.run([self.compiler, '-std=c11', '-Wall', '-Wextra', '-Werror',
                '-fsanitize=undefined', str(source), '-lm', '-o', str(binary)], capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_actual_40_and_49mm_content_excludes_navigation_and_caps_movement(self):
        self.execute('''
for(int small=0;small<2;small++) {
 double w=small?162:211,h=small?197:257,n=small?47.5:66;
 TCWatchListRect v={0,0,w,h},nav={0,0,w,n},empty={0}; TCWatchListDrag p={0};
 TCWatchListRow rows[]={{-1,{2,n,w-4,44}},{-1,{2,small?181:229.5,w-4,small?44:59}}};
 assert(TCWatchListPlan(v,v,nav,0,0,empty,rows,2,&p)==TCWatchListLater);
 assert(p.content.y==n&&p.content.height==h-n);
 assert(p.start.x==w/2&&p.end.x==w/2&&p.start.y-p.end.y<=32);
 assert(p.start.y<h-8&&p.end.y>n+8);
 rows[0]=(TCWatchListRow){1,{2,n+20,w-4,44}};
 assert(TCWatchListPlan(v,v,nav,0,0,empty,rows,1,&p)==TCWatchListEarlier);
 assert(p.end.y>p.start.y&&p.end.y-p.start.y<=32);
}
''')

    def test_retained_source_bound_frames_execute_actual_planner(self):
        fixture = json.loads((ROOT / 'TouchColorWatchUITests/Fixtures/home-list-0eda-frames.json').read_text())
        self.assertEqual(fixture['proposal_base_tree'], '68878c41579a80d64c3ec57cce3ce4fe69c6d4f2')
        self.assertEqual([row['watch_mm'] for row in fixture['cases']], [49, 40])
        for case in fixture['cases']:
            self.assertEqual(len(case['source_sha256']), 64)
            def rect(values):
                return '(TCWatchListRect){' + ','.join(map(str, values)) + '}'
            rows = ','.join('{-1,{' + ','.join(map(str, row['frame'])) + '}}' for row in case['rows'])
            self.execute('TCWatchListDrag p={0}; TCWatchListRow rows[]={' + rows + '};\n'
                + 'assert(TCWatchListPlan(' + ','.join(rect(case[key]) for key in ('viewport', 'collection_view', 'navigation'))
                + ',0,0,(TCWatchListRect){0},rows,3,&p)==TCWatchListLater);')

    def test_current_clipping_shift_and_navigation_changes_are_used(self):
        self.execute('''
TCWatchListRect viewport={10,20,211,257},list={-5,10,240,250},nav={0,15,240,60},content;
assert(TCWatchListContent(viewport,list,nav,&content));
assert(content.x==10&&content.y==75&&content.width==211&&content.height==185);
nav.height=80;assert(TCWatchListContent(viewport,list,nav,&content));assert(content.y==95&&content.height==165);
list=(TCWatchListRect){10,110,211,167};assert(TCWatchListContent(viewport,list,nav,&content));assert(content.y==110&&content.height==167);
list=(TCWatchListRect){10,400,211,257};assert(!TCWatchListContent(viewport,list,nav,&content));
''')

    def test_invalid_empty_nonfinite_and_tiny_frames_fail_closed(self):
        self.execute('''
TCWatchListRect v={0,0,211,257},nav={0,0,211,66},content;
TCWatchListRect bad[]={{NAN,0,211,257},{0,INFINITY,211,257},{0,0,0,257},{0,0,211,-1},{1e308,0,1e308,257}};
for(size_t i=0;i<sizeof(bad)/sizeof(*bad);i++) {
 assert(!TCWatchListContent(bad[i],v,nav,&content));
 assert(!TCWatchListContent(v,bad[i],nav,&content));
 assert(!TCWatchListContent(v,v,bad[i],&content));
}
assert(!TCWatchListContent(v,v,(TCWatchListRect){0,0,211,250},&content));
assert(!TCWatchListContent(v,v,(TCWatchListRect){40,0,100,66},&content));
assert(!TCWatchListContent(v,v,(TCWatchListRect){0,80,211,66},&content));
assert(!TCWatchListContent(v,v,(TCWatchListRect){0,-100,211,20},&content));
assert(!TCWatchListContent(v,v,nav,NULL));
''')

    def test_target_clipping_ready_and_unreachable_horizontal_geometry(self):
        self.execute('''
TCWatchListRect v={0,0,211,257},nav={0,0,211,66};TCWatchListDrag p={0};
assert(TCWatchListPlan(v,v,nav,0,1,(TCWatchListRect){2,250,207,44},NULL,0,&p)==TCWatchListLater);
assert(TCWatchListPlan(v,v,nav,0,1,(TCWatchListRect){2,40,207,44},NULL,0,&p)==TCWatchListEarlier);
assert(TCWatchListPlan(v,v,nav,0,1,(TCWatchListRect){2,65,207,44},NULL,0,&p)==TCWatchListEarlier);
assert(p.end.y-p.start.y==12);
assert(TCWatchListPlan(v,v,nav,0,1,(TCWatchListRect){2,66,207,44},NULL,0,&p)==TCWatchListReady);
assert(TCWatchListPlan(v,v,nav,0,1,(TCWatchListRect){2,120,207,44},NULL,0,&p)==TCWatchListReady);
TCWatchListRect bad[]={{-1,120,207,44},{2,120,220,44},{2,10,207,300},{2,NAN,207,44},{2,120,207,0}};
for(size_t i=0;i<sizeof(bad)/sizeof(*bad);i++)assert(TCWatchListPlan(v,v,nav,0,1,bad[i],NULL,0,&p)==TCWatchListAmbiguous);
''')

    def test_missing_target_uses_visible_consistent_neighbors_only(self):
        self.execute('''
TCWatchListRect v={0,0,162,197},nav={0,0,162,47.5},empty={0};TCWatchListDrag p={0};
TCWatchListRow rows[]={{-1,{2,50,158,44}},{1,{2,100,158,44}}};
assert(TCWatchListPlan(v,v,nav,0,0,empty,rows,2,&p)==TCWatchListAmbiguous);
assert(TCWatchListPlan(v,v,nav,1,0,empty,rows,2,&p)==TCWatchListAmbiguous);
assert(TCWatchListPlan(v,v,nav,2,0,empty,rows,2,&p)==TCWatchListLater);
rows[0].frame.y=-100;assert(TCWatchListPlan(v,v,nav,0,0,empty,rows,2,&p)==TCWatchListEarlier);
rows[0]=(TCWatchListRow){INT_MAX,{2,90,158,44}};
assert(TCWatchListPlan(v,v,nav,0,0,empty,rows,1,&p)==TCWatchListEarlier);
rows[0].frame.y=197;assert(TCWatchListPlan(v,v,nav,0,0,empty,rows,1,&p)==TCWatchListAmbiguous);
rows[0].frame.y=195;assert(TCWatchListPlan(v,v,nav,0,0,empty,rows,1,&p)==TCWatchListEarlier);
rows[0].frame.x=200;assert(TCWatchListPlan(v,v,nav,0,0,empty,rows,1,&p)==TCWatchListAmbiguous);
assert(TCWatchListPlan(v,v,nav,0,0,empty,NULL,0,&p)==TCWatchListAmbiguous);
assert(TCWatchListPlan(v,v,nav,0,0,empty,NULL,1,&p)==TCWatchListAmbiguous);
assert(TCWatchListPlan(v,v,nav,0,0,empty,rows,25,&p)==TCWatchListAmbiguous);
''')

    def test_all_valid_window_sizes_keep_endpoints_in_content(self):
        self.execute('''
for(int w=40;w<300;w+=7)for(int h=100;h<350;h+=11)for(int n=10;n<h-60;n+=13) {
 TCWatchListRect v={13,17,w,h},nav={13,17,w,n},empty={0};TCWatchListDrag p={0};
 TCWatchListRow row={-1,{14,17+n,w-2,44}};
 assert(TCWatchListPlan(v,v,nav,0,0,empty,&row,1,&p)==TCWatchListLater);
 assert(p.start.x>13&&p.end.x<13+w&&p.end.y>17+n+8&&p.start.y<17+h-8);
 assert(p.start.y-p.end.y<=32.00000001&&p.start.y>p.end.y);
}
''')

    def test_live_snapshot_scope_hittability_and_final_twelfth_observation_are_required(self):
        source = (ROOT / 'TouchColorWatchUITests/WatchWorkflowTests.swift').read_text()
        helper = source.split('private func reachSavedColorByTouch(', 1)[1].split('    @MainActor func testEditSavedCopy', 1)[0]
        self.assertEqual(helper.count('app.snapshot()'), 1)
        for expected in ('for attempt in 0...12', 'guard attempt < 12', 'visited <= 512',
                         'Double(value.size.width)', 'Double(value.size.height)',
                         'rows.count < 24', 'seen.insert(id).inserted', 'element.elementType == .collectionView',
                         'XCTAssertEqual(lists.count, 1', 'XCTAssertEqual(navigation.count, 1',
                         'XCTAssertEqual(listQuery.count, 1)', 'XCTAssertTrue(button.isHittable)',
                         'TCWatchListContains(plan.content, rect(button.frame))',
                         'XCTAssertEqual(list.frame, listFrame)', 'XCTAssertEqual(start.screenPoint',
                         'thenHoldForDuration: 0.15'):
            self.assertIn(expected, helper)
        self.assertLess(helper.index('if decision == TCWatchListReady'), helper.index('guard attempt < 12'))
        self.assertEqual(helper.count('start.press('), 1)
        for forbidden in ('swipeUp', 'swipeDown', 'rotateDigitalCrown', 'focus', 'XCTSkip', 'XCTExpectFailure'):
            self.assertNotIn(forbidden, helper)
        self.assertIn('name.contains("Chinese") ? 240 : 120', source)
        touch = source.split('func testTouchEditSavedCopyDeleteOneDuplicateAndRelaunchKeepsOrder()', 1)[1]
        self.assertIn('try reachSavedColorByTouch(identifier)', touch)
        self.assertIn('try reachSavedColorByTouch("watch.color.1", tap: false)', touch)
        self.assertNotIn('for _ in 0..<4 { app.swipeDown() }', touch)
        self.assertNotIn('rotateDigitalCrown', touch)

    def test_native_and_portable_registration_is_test_only(self):
        generator = (ROOT / 'scripts/generate_watch_project.py').read_text()
        project = (ROOT / 'TouchColorWatch.xcodeproj/project.pbxproj').read_text()
        hosted = (ROOT / 'TouchColorWatchTests/WatchWorkspaceTests.swift').read_text()
        entry = (ROOT / 'scripts/test_watch_profiles.py').read_text()
        self.assertEqual(project.count('"SWIFT_OBJC_BRIDGING_HEADER" = "TouchColorWatchUITests/TCWatchListDragGeometry.h"'), 4)
        self.assertIn("if not app:", generator)
        self.assertEqual(hosted.count('func testTouchListDragGeometryUsesCurrentContentAndRejectsAmbiguity()'), 1)
        self.assertIn('from test_watch_touch_drag import WatchTouchDragTests', entry)
        self.assertIn('loader.loadTestsFromTestCase(WatchTouchDragTests)', entry)
        hosted_inventory = sum(len(re.findall(r'func test\w+\s*\(', path.read_text()))
            for directory in ('TouchColorWatchTests', 'Packages/ColorCore/Tests')
            for path in (ROOT / directory).rglob('*.swift'))
        self.assertEqual(hosted_inventory, 52)
        self.assertIn('summary_counts(hosted, device, 52, hosted_skipped)',
            (ROOT / 'scripts/native_text_evidence.py').read_text())
        for path in (ROOT / 'TouchColorWatch').rglob('*.swift'):
            self.assertNotIn('TCWatchList', path.read_text())


    def test_exact_1410_failures_select_only_geometry_without_inventing_hittability(self):
        fixture = json.loads((ROOT / 'TouchColorWatchUITests/Fixtures/home-list-1410-touch-anchor.json').read_text())
        self.assertEqual(fixture['observed_source_commit'], '1410ed01f0d153be79cbd688c3385320670d7367')
        self.assertEqual(fixture['proposal_base_commit'], 'e9805ac4f497f19fb7ab4002d5a1aeaaf04ee700')
        self.assertEqual(fixture['proposal_base_tree'], 'ef1f72f98d01cc59a2cdc54e22a89df89474bf61')
        self.assertEqual([(c['watch_mm'], c['job_id'], c['artifact_id'], c['failure_seconds']) for c in fixture['cases']],
            [(40, 111596149429, 11324518289, 10.630), (49, 111596149454, 11324284355, 9.400)])
        for case in fixture['cases']:
            self.assertFalse(case['collection_view_hittable'])
            self.assertFalse(case['descendant_hittability_observed'])
            self.assertFalse(case['target_in_snapshot'])
            self.assertEqual(case['target_identifier'], 'watch.color.0')
            self.assertEqual(case['geometric_anchor_identifier'], 'watch.photo')
            self.assertEqual([r['identifier'] for r in case['rows']], ['watch.editor', 'watch.photo', 'watch.count'])
            for key in ('source_log_sha256', 'artifact_sha256', 'summary_sha256', 'screenshot_sha256'):
                self.assertRegex(case[key], r'^[a-f0-9]{64}$')
            # The exact failure hierarchy, not a guessed post-scroll hierarchy.
            for row in case['rows']:
                self.assertIsNone(row['live_hittable'])
                match = re.search(row['type'] + r', .*?\{\{([-.\d]+), ([-.\d]+)\}, \{([-.\d]+), ([-.\d]+)\}\}, identifier: '
                    + re.escape("'" + row['identifier'] + "'"), case['failure_ax_excerpt'])
                self.assertIsNotNone(match)
                self.assertEqual([float(x) for x in match.groups()], row['frame'])
            rect = lambda values: '(TCWatchListRect){' + ','.join(map(str, values)) + '}'
            frames = ','.join(rect(row['frame']) for row in case['rows'])
            rows = ','.join('{-1,' + rect(row['frame']) + '}' for row in case['rows'])
            start, end = case['expected_plan']['start'], case['expected_plan']['end']
            self.execute('TCWatchListDrag p={0}; TCWatchListRect frames[]={' + frames + '};\n'
                + 'TCWatchListRow rows[]={' + rows + '};\n'
                + 'assert(TCWatchListPlan(' + ','.join(rect(case[key]) for key in ('viewport', 'collection_view', 'navigation'))
                + ',0,0,(TCWatchListRect){0},rows,3,&p)==TCWatchListLater);\n'
                + f'assert(p.start.x=={start[0]}&&p.start.y=={start[1]}&&p.end.x=={end[0]}&&p.end.y=={end[1]});\n'
                + '''TCWatchListDrag before=p;
assert(TCWatchListTouchAnchorIndex(&p,frames,3)==1);
/* Historical evidence has no live descendant observation. Simulated false/true
   state only exercises the actual validation helper, not native acceptance. */
assert(!TCWatchListTouchAnchorReady(&p,frames[1],frames[1],1,1,0,1));
assert(TCWatchListTouchAnchorReady(&p,frames[1],frames[1],1,1,1,1));
assert(p.start.x==before.start.x&&p.start.y==before.start.y);
assert(p.end.x==before.end.x&&p.end.y==before.end.y&&p.direction==before.direction);
assert(p.content.x==before.content.x&&p.content.y==before.content.y);
assert(p.content.width==before.content.width&&p.content.height==before.content.height);
''')

    def test_touch_anchor_gap_none_ambiguous_duplicate_and_clipped_fail_closed(self):
        self.execute('''
TCWatchListDrag p={{0,47.5,162,149.5},{81,138.25},{81,106.25},1};
TCWatchListRect photo={2,95.5,158,47},frames[]={photo,photo};
assert(TCWatchListTouchAnchorIndex(&p,frames,1)==0);
assert(TCWatchListTouchAnchorIndex(&p,frames,2)==-1); /* duplicate */
frames[1]=(TCWatchListRect){40,130,80,25};
assert(TCWatchListTouchAnchorIndex(&p,frames,2)==-1); /* distinct overlap */
frames[0]=(TCWatchListRect){2,47.5,158,44};frames[1]=(TCWatchListRect){2,181,158,44};
assert(TCWatchListTouchAnchorIndex(&p,frames,2)==-1); /* planned start in gap */
frames[0]=(TCWatchListRect){2,40,158,110};
assert(TCWatchListTouchAnchorIndex(&p,frames,1)==-1); /* clipped by navigation */
frames[0]=(TCWatchListRect){2,130,158,100};
assert(TCWatchListTouchAnchorIndex(&p,frames,1)==-1); /* clipped by bottom */
frames[0]=photo;p.start.y=photo.y;
assert(TCWatchListTouchAnchorIndex(&p,frames,1)==-1); /* border is not interior */
p.start.y=photo.y+photo.height;
assert(TCWatchListTouchAnchorIndex(&p,frames,1)==-1);
assert(TCWatchListTouchAnchorIndex(&p,NULL,0)==-1);
assert(TCWatchListTouchAnchorIndex(&p,frames,0)==-1);
assert(TCWatchListTouchAnchorIndex(&p,frames,25)==-1);
assert(TCWatchListTouchAnchorIndex(NULL,frames,1)==-1);
''')

    def test_touch_anchor_malformed_frames_points_and_decisions_fail_closed(self):
        self.execute('''
TCWatchListDrag p={{0,47.5,162,149.5},{81,138.25},{81,106.25},1},good=p;
TCWatchListRect photo={2,95.5,158,47};
TCWatchListRect bad[]={{NAN,95.5,158,47},{2,INFINITY,158,47},{2,95.5,0,47},
 {2,95.5,158,-1},{1e308,0,1e308,47}};
for(size_t i=0;i<sizeof(bad)/sizeof(*bad);i++) {
 assert(TCWatchListTouchAnchorIndex(&p,&bad[i],1)==-1);
 assert(!TCWatchListTouchAnchorReady(&p,photo,bad[i],1,1,1,1));
}
p.start.x=NAN;assert(TCWatchListTouchAnchorIndex(&p,&photo,1)==-1);
p=good;p.end.y=INFINITY;assert(TCWatchListTouchAnchorIndex(&p,&photo,1)==-1);
p=good;p.content.width=-1;assert(TCWatchListTouchAnchorIndex(&p,&photo,1)==-1);
p=good;p.start.y=20;assert(TCWatchListTouchAnchorIndex(&p,&photo,1)==-1);
p=good;p.end.y=20;assert(TCWatchListTouchAnchorIndex(&p,&photo,1)==-1);
p=good;p.direction=TCWatchListReady;assert(TCWatchListTouchAnchorIndex(&p,&photo,1)==-1);
p=good;p.direction=TCWatchListAmbiguous;assert(TCWatchListTouchAnchorIndex(&p,&photo,1)==-1);
assert(!TCWatchListTouchAnchorReady(NULL,photo,photo,1,1,1,1));
''')

    def test_touch_anchor_occluded_stale_duplicate_missing_and_wrong_home_are_rejected(self):
        self.execute('''
TCWatchListDrag p={{0,47.5,162,149.5},{81,138.25},{81,106.25},1};
TCWatchListRect photo={2,95.5,158,47},live=photo;
assert(TCWatchListTouchAnchorReady(&p,photo,live,1,1,1,1));
assert(!TCWatchListTouchAnchorReady(&p,photo,live,0,1,1,1));
assert(!TCWatchListTouchAnchorReady(&p,photo,live,2,1,1,1));
assert(!TCWatchListTouchAnchorReady(&p,photo,live,1,0,1,1));
assert(!TCWatchListTouchAnchorReady(&p,photo,live,1,1,0,1)); /* occluded/not hittable */
assert(!TCWatchListTouchAnchorReady(&p,photo,live,1,1,1,0)); /* wrong home or overlay */
assert(!TCWatchListTouchAnchorReady(&p,photo,live,1,2,1,1));
assert(!TCWatchListTouchAnchorReady(&p,photo,live,1,1,2,1));
assert(!TCWatchListTouchAnchorReady(&p,photo,live,1,1,1,2));
live.x+=0.5;assert(!TCWatchListTouchAnchorReady(&p,photo,live,1,1,1,1));
live=photo;live.y+=0.5;assert(!TCWatchListTouchAnchorReady(&p,photo,live,1,1,1,1));
live=photo;live.width-=0.5;assert(!TCWatchListTouchAnchorReady(&p,photo,live,1,1,1,1));
live=photo;live.height-=0.5;assert(!TCWatchListTouchAnchorReady(&p,photo,live,1,1,1,1));
''')

    def test_touch_anchor_live_xcui_binding_and_overlay_checks_precede_only_dispatch(self):
        source = (ROOT / 'TouchColorWatchUITests/WatchWorkflowTests.swift').read_text()
        helper = source.split('private func reachSavedColorByTouch(', 1)[1].split('    @MainActor func testEditSavedCopy', 1)[0]
        for expected in ('element.children.isEmpty', 'element.elementType == expectedType',
                         'identifier == "watch.color.\\(targetIndex)"',
                         'TCWatchListSelectTouch(&plan, rowFrames.baseAddress, rowFrames.count,',
                         'guard anchorIndex >= 0', 'coveringLeaves.count == 1',
                         'coveringLeaves[0].id == captured.id', 'coveringLeaves[0].type == captured.type',
                         'coveringLeaves[0].frame == captured.frame',
                         'list.descendants(matching: .any).matching(identifier: captured.id)',
                         'guard anchorQuery.count == 1', 'let anchor = anchorQuery.element',
                         'anchor.exists', 'anchor.identifier == captured.id', 'anchor.elementType == captured.type',
                         'anchor.isHittable', 'liveFrame = anchor.frame',
                         'app.navigationBars.count == 1', 'app.navigationBars["TouchColor"].exists',
                         '!app.buttons["BackButton"].exists', 'app.alerts.count == 0', 'app.sheets.count == 0',
                         'guard currentHome(), currentTarget() else { return false }',
                         'TCWatchListTouchAnchorReady(&gesture, rect(captured.frame), rect(liveFrame)',
                         'diagnostic("REJECT",', 'diagnostic.prefix(4096)', 'live=\\(liveAnchorState)'):
            self.assertIn(expected, helper)
        self.assertEqual(helper.count('guard anchorReady() else'), 2)
        self.assertLess(helper.rindex('guard anchorReady() else'), helper.index('start.press('))
        self.assertGreater(helper.rindex('guard anchorReady() else'), helper.index('XCTAssertEqual(end.screenPoint'))
        self.assertEqual(helper.count('app.snapshot()'), 1)
        for forbidden in ('XCTAssertTrue(list.isHittable)', '.firstMatch', 'anchor.tap()', 'anchor.press(',
                          'hitPoint', 'value(forKey:', 'perform(', 'plan.start =', 'plan.end ='):
            self.assertNotIn(forbidden, helper)
        # Unknown semantic leaves can reject an overlap, never become a fallback.
        self.assertIn('semanticLeaves.filter { TCWatchListPointTouches(rect($0.frame), gesture.start) != 0 }', helper)
        self.assertIn('failAnchor("overlapping-snapshot-leaf"); return', helper)

    def test_touch_anchor_delta_preserves_all_other_methods_and_original_geometry(self):
        import hashlib
        source = (ROOT / 'TouchColorWatchUITests/WatchWorkflowTests.swift').read_text()
        begin = source.index('    @MainActor private func reachSavedColorByTouch(')
        end = source.index('    @MainActor func testEditSavedCopy', begin)
        self.assertEqual(hashlib.sha256((source[:begin] + source[end:]).encode()).hexdigest(),
            'b20ea327a2f1d6e3cd9a5963738e1c5aeb064d92f99c27a13c7e54635f582793')
        header = HEADER.read_text()
        original = header.split('/* Validation only: keep the already planned path byte-for-byte unchanged.', 1)[0] + '#endif\n'
        self.assertEqual(hashlib.sha256(original.encode()).hexdigest(),
            '2ce0ef79c234888cdf500257fa84a6a6123bc3070c769dd356c202cecec30894')
        validation = header[len(original) - len('#endif\n'):]
        self.assertNotRegex(validation, r'plan->\w+(?:\.\w+)?\s*=(?!=)')


    def test_adaptive_exact_da9570_gap_states_keep_prior_dispatch_provenance(self):
        fixture = json.loads((ROOT / 'TouchColorWatchUITests/Fixtures/home-list-da9570-adaptive-touch-anchor.json').read_text())
        self.assertEqual(fixture['baseline_commit'], 'da9570f2a162f0e05f59b41a1ec578f8ce47af73')
        self.assertEqual([(c['watch_mm'], c['job_id']) for c in fixture['cases']],
                         [(40, 111646725030), (49, 111646725051)])
        expected = {40: ([81, 97], [81, 65]), 49: ([105.5, 137.5], [105.5, 105.5])}
        rectangle = lambda r: '(TCWatchListRect){' + ','.join(map(str, r)) + '}'
        for case in fixture['cases']:
            observed, proposed = case['direct_rejection'], case['expected_proposal']
            self.assertFalse(case['direct_prior_dispatch']['same_case_initial_row_frames_retained'])
            self.assertIn('Press CollectionView', case['direct_prior_dispatch']['log_line'])
            self.assertRegex(case['direct_prior_dispatch']['omitted_exported_ui_snapshot'], r'^[A-F0-9-]{36}$')
            self.assertLess(case['direct_prior_dispatch']['line_number'], observed['line_number'])
            self.assertEqual(observed['attempt'], 1)
            self.assertEqual(observed['target_identifier'], 'watch.color.1')
            self.assertFalse(observed['target_in_snapshot'])
            self.assertEqual(observed['live_anchor_state'], 'not-queried')
            self.assertEqual((proposed['start'], proposed['end']), expected[case['watch_mm']])
            self.assertEqual(proposed['status'], 'calculated; never dispatched')
            self.assertTrue(proposed['requires_new_live_validation'])
            for item in case['evidence'].values():
                self.assertRegex(item['sha256'], r'^[a-f0-9]{64}$')
            self.assertRegex(case['uploaded_artifact_sha256'], r'^[a-f0-9]{64}$')
            for row in observed['rows']:
                self.assertIsNone(row['live_hittable'])
                captured = re.search(re.escape(row['identifier']) + r'=\(([^)]+)\)', observed['log_line'])
                self.assertIsNotNone(captured)
                self.assertEqual(list(map(float, captured[1].split(','))), row['frame'])
                ax = re.search(row['type'] + r', .*?\{\{([-.\d]+), ([-.\d]+)\}, \{([-.\d]+), ([-.\d]+)\}\}, identifier: '
                               + re.escape("'" + row['identifier'] + "'"), case['failure_ax_excerpt'])
                self.assertIsNotNone(ax)
                self.assertEqual(list(map(float, ax.groups())), row['frame'])
            initial = case['historical_initial_geometry_reference']
            self.assertEqual(initial['source_commit'], '1410ed01f0d153be79cbd688c3385320670d7367')
            self.assertIn('not same-case', initial['relationship'])
            # Historical original-path preservation and a fresh actual gap state
            # are separate observations, not an invented same-case frame pair.
            initial_frames = ','.join(rectangle(row['frame']) for row in initial['rows'])
            gap_frames = ','.join(rectangle(row['frame']) for row in observed['rows'])
            start, end = proposed['start'], proposed['end']
            self.execute('''
TCWatchListDrag original={0}, out={0}; int mode=7;
TCWatchListRect initial[]={''' + initial_frames + '}, gap[]={' + gap_frames + '''};
TCWatchListRow rows[3]; for(int i=0;i<3;i++) rows[i]=(TCWatchListRow){-1,initial[i]};
assert(TCWatchListPlan(''' + ','.join(rectangle(observed[k]) for k in ('viewport', 'collection_view', 'navigation')) + ''',1,0,(TCWatchListRect){0},rows,3,&original)==TCWatchListLater);
TCWatchListDrag saved=original;
assert(TCWatchListSelectTouch(&original,initial,3,initial,3,&out,&mode)==1&&mode==0);
assert(out.start.x==original.start.x&&out.start.y==original.start.y&&out.end.x==original.end.x&&out.end.y==original.end.y);
for(int i=0;i<3;i++) rows[i].frame=gap[i];
assert(TCWatchListPlan(''' + ','.join(rectangle(observed[k]) for k in ('viewport', 'collection_view', 'navigation')) + ''',1,0,(TCWatchListRect){0},rows,3,&original)==TCWatchListLater);
assert(TCWatchListTouchAnchorIndex(&original,gap,3)==-1);
assert(TCWatchListSelectTouch(&original,gap,3,gap,3,&out,&mode)==1&&mode==1);
''' + f'assert(out.start.x=={start[0]}&&out.start.y=={start[1]}&&out.end.x=={end[0]}&&out.end.y=={end[1]});\n' + '''
assert(original.start.x==saved.start.x&&original.start.y==saved.start.y&&original.end.x==saved.end.x&&original.end.y==saved.end.y);
assert(!TCWatchListTouchAnchorReady(&out,gap[1],gap[1],1,1,0,1));
/* Synthetic live truth tests the validator, never asserts observed hittability. */
assert(TCWatchListTouchAnchorReady(&out,gap[1],gap[1],1,1,1,1));
''')

    def test_adaptive_covered_plan_is_preserved_before_ranking(self):
        self.execute('''
TCWatchListDrag p={{0,47.5,162,149.5},{81,138.25},{81,106.25},1},out={0};int mode=7;
TCWatchListRect rows[]={{2,95.5,158,47},{2,139,158,2}};
assert(TCWatchListSelectTouch(&p,rows,2,rows,2,&out,&mode)==0&&mode==0);
assert(out.start.x==p.start.x&&out.start.y==p.start.y&&out.end.x==p.end.x&&out.end.y==p.end.y);
assert(TCWatchListSameRect(out.content,p.content)&&out.direction==p.direction);
/* Same preservation under a nonzero viewport origin. */
p.content.x+=13;p.content.y+=17;p.start.x+=13;p.end.x+=13;p.start.y+=17;p.end.y+=17;
for(int i=0;i<2;i++){rows[i].x+=13;rows[i].y+=17;}
assert(TCWatchListSelectTouch(&p,rows,2,rows,2,&out,&mode)==0&&mode==0);
assert(out.start.x==p.start.x&&out.start.y==p.start.y&&out.end.x==p.end.x&&out.end.y==p.end.y);
''')

    def test_adaptive_unique_nearest_is_order_independent_and_ties_fail(self):
        self.execute('''
TCWatchListDrag p={{0,47.5,162,149.5},{81,138.25},{81,106.25},1},out={0};int mode=7;
TCWatchListRect rows[]={{2,80,158,20},{2,160,158,20}}, reverse[]={rows[1],rows[0]};
assert(TCWatchListSelectTouch(&p,rows,2,rows,2,&out,&mode)==1&&mode==1);
assert(out.start.y==170&&out.end.y==138);
assert(TCWatchListSelectTouch(&p,reverse,2,reverse,2,&out,&mode)==0&&mode==1);
assert(out.start.y==170&&out.end.y==138);
rows[0].y=88.25;rows[1].y=168.25;
out=p;mode=7;
assert(TCWatchListSelectTouch(&p,rows,2,rows,2,&out,&mode)==-1&&mode==7);
assert(out.start.y==p.start.y&&out.end.y==p.end.y);
reverse[0]=rows[1];reverse[1]=rows[0];
assert(TCWatchListSelectTouch(&p,reverse,2,reverse,2,&out,&mode)==-1&&mode==7);
''')

    def test_adaptive_only_genuine_gap_allows_fallback(self):
        self.execute('''
TCWatchListDrag p={{0,47.5,162,149.5},{81,138.25},{81,106.25},1},out={0};int mode=7;
TCWatchListRect safe={2,73.5,158,47}, rows[]={safe,{2,40,158,110}};
/* Another safe row cannot excuse a clipped or duplicate cover at original start. */
assert(TCWatchListSelectTouch(&p,rows,2,rows,2,&out,&mode)==-1);
rows[1]=(TCWatchListRect){2,130,158,100};
assert(TCWatchListSelectTouch(&p,rows,2,rows,2,&out,&mode)==-1);
rows[1]=(TCWatchListRect){2,138.25,158,20};
assert(TCWatchListSelectTouch(&p,rows,2,rows,2,&out,&mode)==-1); /* top border */
rows[1]=(TCWatchListRect){2,118.25,158,20};
assert(TCWatchListSelectTouch(&p,rows,2,rows,2,&out,&mode)==-1); /* bottom border */
rows[0]=(TCWatchListRect){2,95.5,158,47};rows[1]=rows[0];
assert(TCWatchListSelectTouch(&p,rows,2,rows,2,&out,&mode)==-1);
rows[1]=(TCWatchListRect){30,130,100,20};
assert(TCWatchListSelectTouch(&p,rows,2,rows,2,&out,&mode)==-1); /* distinct overlap */
TCWatchListRect leaves[]={safe,{70,130,20,20}};
assert(TCWatchListSelectTouch(&p,&safe,1,leaves,2,&out,&mode)==-1); /* unknown original cover */
leaves[1]=(TCWatchListRect){81,138.25,20,20};
assert(TCWatchListSelectTouch(&p,&safe,1,leaves,2,&out,&mode)==-1); /* unknown border */
assert(mode==7);
''')

    def test_adaptive_candidate_visibility_semantic_overlap_and_room_fail_closed(self):
        self.execute('''
TCWatchListDrag p={{0,47.5,162,149.5},{81,138.25},{81,106.25},1},out={0};int mode=7;
TCWatchListRect row={2,73.5,158,47}, leaves[]={row,{70,90,20,20}};
assert(TCWatchListSelectTouch(&p,&row,1,leaves,2,&out,&mode)==-1); /* foreign proposed cover */
leaves[1]=(TCWatchListRect){81,97,20,20};
assert(TCWatchListSelectTouch(&p,&row,1,leaves,2,&out,&mode)==-1); /* foreign border */
leaves[1]=row;
assert(TCWatchListSelectTouch(&p,&row,1,leaves,2,&out,&mode)==-1); /* duplicated leaf */
leaves[0]=(TCWatchListRect){2,73.5,158,46};
assert(TCWatchListSelectTouch(&p,&row,1,leaves,1,&out,&mode)==-1); /* different semantic frame */
TCWatchListRect bad[]={{2,40,158,44},{2,180,158,44},{90,80,50,40},{2,47.5,158,40},{2,69.5,158,20}};
for(size_t i=0;i<sizeof(bad)/sizeof(*bad);i++)
 assert(TCWatchListSelectTouch(&p,&bad[i],1,&bad[i],1,&out,&mode)==-1);
/* Row midpoint 79.5 would end exactly on navigation boundary 47.5. */
assert(mode==7);
p=(TCWatchListDrag){{0,47.5,162,149.5},{81,106.25},{81,138.25},-1};
row=(TCWatchListRect){2,173,158,20};
assert(TCWatchListSelectTouch(&p,&row,1,&row,1,&out,&mode)==-1); /* reverse end outside */
''')

    def test_adaptive_malformed_inputs_leave_plan_and_outputs_unchanged(self):
        self.execute('''
TCWatchListDrag good={{0,47.5,162,149.5},{81,138.25},{81,106.25},1},p=good,out=good;
TCWatchListRect row={2,73.5,158,47};int mode=7;
assert(TCWatchListSelectTouch(NULL,&row,1,&row,1,&out,&mode)==-1);
assert(TCWatchListSelectTouch(&p,NULL,1,&row,1,&out,&mode)==-1);
assert(TCWatchListSelectTouch(&p,&row,0,&row,1,&out,&mode)==-1);
assert(TCWatchListSelectTouch(&p,&row,25,&row,1,&out,&mode)==-1);
assert(TCWatchListSelectTouch(&p,&row,1,NULL,1,&out,&mode)==-1);
assert(TCWatchListSelectTouch(&p,&row,1,&row,0,&out,&mode)==-1);
assert(TCWatchListSelectTouch(&p,&row,1,&row,513,&out,&mode)==-1);
assert(TCWatchListSelectTouch(&p,&row,1,&row,1,NULL,&mode)==-1);
assert(TCWatchListSelectTouch(&p,&row,1,&row,1,&out,NULL)==-1);
assert(TCWatchListSelectTouch(&p,&row,1,&row,1,&p,&mode)==-1);
TCWatchListRect bad[]={{NAN,80,158,40},{2,INFINITY,158,40},{2,80,0,40},{2,80,158,-1},{1e308,80,1e308,40}};
for(size_t i=0;i<sizeof(bad)/sizeof(*bad);i++) {
 assert(TCWatchListSelectTouch(&p,&bad[i],1,&row,1,&out,&mode)==-1);
 assert(TCWatchListSelectTouch(&p,&row,1,&bad[i],1,&out,&mode)==-1);
}
for(int n=0;n<10;n++) {
 p=good;
 switch(n){case 0:p.start.x=NAN;break;case 1:p.end.y=INFINITY;break;
 case 2:p.content.width=0;break;case 3:p.direction=2;break;case 4:p.direction=0;break;
 case 5:p.direction=-1;break;case 6:p.end.x+=1;break;case 7:p.end=p.start;break;
 case 8:p.end.y-=1;break;case 9:p.start.y=20;break;}
 assert(TCWatchListSelectTouch(&p,&row,1,&row,1,&out,&mode)==-1);
}
assert(mode==7&&out.start.y==good.start.y&&out.end.y==good.end.y);
''')

    def test_adaptive_both_directions_and_clipped_target_reveal_distance(self):
        self.execute('''
TCWatchListRect v={0,0,211,257},nav={0,0,211,66};TCWatchListDrag p={0},out={0};int mode=7;
TCWatchListRect earlierRow={2,180,207,30},laterRow={2,108,207,59};
assert(TCWatchListPlan(v,v,nav,0,1,(TCWatchListRect){2,65,207,44},NULL,0,&p)==TCWatchListEarlier);
assert(p.end.y-p.start.y==12);
assert(TCWatchListSelectTouch(&p,&earlierRow,1,&earlierRow,1,&out,&mode)==0&&mode==1);
assert(out.start.y==195&&out.end.y==207&&out.direction==-1);
assert(TCWatchListPlan(v,v,nav,0,1,(TCWatchListRect){2,214,207,44},NULL,0,&p)==TCWatchListLater);
assert(p.end.y-p.start.y==-12);
assert(TCWatchListSelectTouch(&p,&laterRow,1,&laterRow,1,&out,&mode)==0&&mode==1);
assert(out.start.y==137.5&&out.end.y==125.5&&out.direction==1);
p=(TCWatchListDrag){{0,47.5,162,149.5},{81,106.25},{81,138.25},-1};
earlierRow=(TCWatchListRect){2,130,158,44};
assert(TCWatchListSelectTouch(&p,&earlierRow,1,&earlierRow,1,&out,&mode)==0&&mode==1);
assert(out.start.y==152&&out.end.y==184);
''')

    def test_adaptive_actual_planner_property_grid_keeps_exact_delta_and_content(self):
        self.execute('''
for(int width=40;width<260;width+=13)for(int height=100;height<330;height+=17)for(int navHeight=10;navHeight<height-60;navHeight+=19)for(int direction=-1;direction<=1;direction+=2){
 TCWatchListRect v={13,17,width,height},nav={13,17,width,navHeight};TCWatchListDrag p={0},out={0};int mode=7;
 TCWatchListRow observed={direction==1?-1:INT_MAX,{14,17+navHeight,width-2,20}};
 assert(TCWatchListPlan(v,v,nav,0,0,(TCWatchListRect){0},&observed,1,&p)==direction);
 double delta=p.end.y-p.start.y,mid=p.content.y+p.content.height*.5;
 double rowMid=mid-delta;
 TCWatchListRect row={14,rowMid-fabs(delta)*.25,width-2,fabs(delta)*.5};
 TCWatchListDrag original=p;
 int selected=TCWatchListSelectTouch(&p,&row,1,&row,1,&out,&mode);
 double proposedStart=row.y+row.height*.5,proposedEnd=proposedStart+delta;
 if(proposedEnd-proposedStart!=delta){
  assert(selected==-1&&mode==7&&out.start.y==0&&out.end.y==0);
  /* Never silently relax exact signed distance to fit rounded midpoint math. */
  continue;
 }
 assert(selected==0&&mode==1);
 assert(out.direction==direction&&out.start.x==p.start.x&&out.end.x==p.end.x);
 assert(out.end.y-out.start.y==delta&&fabs(delta)<=32);
 assert(fabs(delta)<=p.content.height*.22+1e-12);
 assert(TCWatchListPointInside(p.content,out.start)&&TCWatchListPointInside(p.content,out.end));
 assert(TCWatchListSameRect(out.content,p.content)&&TCWatchListContains(p.content,row));
 assert(p.start.x==original.start.x&&p.start.y==original.start.y&&p.end.x==original.end.x&&p.end.y==original.end.y);
}
''')

    def test_adaptive_rounding_rejects_inexact_translation_and_preserves_covered_path(self):
        self.execute('''
TCWatchListRect v={13,17,40,100},nav={13,17,40,10};
TCWatchListRow observed={-1,{14,27,38,20}};
TCWatchListDrag p={0},out={0};int mode=7;
assert(TCWatchListPlan(v,v,nav,0,0,(TCWatchListRect){0},&observed,1,&p)==1);
double delta=p.end.y-p.start.y,mid=p.content.y+p.content.height*.5;
TCWatchListRect row={14,mid-delta-fabs(delta)*.25,38,fabs(delta)*.5};
double start=row.y+row.height*.5;
assert((start+delta)-start!=delta);
assert(TCWatchListSelectTouch(&p,&row,1,&row,1,&out,&mode)==-1&&mode==7);
assert(out.start.y==0&&out.end.y==0);
row=(TCWatchListRect){14,p.start.y-2,38,4};
assert(TCWatchListSelectTouch(&p,&row,1,&row,1,&out,&mode)==0&&mode==0);
assert(out.start.y==p.start.y&&out.end.y==p.end.y);
''')

    def test_adaptive_row_and_semantic_bounds_accept_exact_limits(self):
        self.execute('''
TCWatchListDrag p={{0,47.5,162,149.5},{81,138.25},{81,106.25},1},out={0};int mode=7;
TCWatchListRect rows[24],leaves[512];
rows[0]=(TCWatchListRect){2,73.5,158,47};leaves[0]=rows[0];
for(int i=1;i<24;i++)rows[i]=(TCWatchListRect){300,400+i*2,1,1};
for(int i=1;i<512;i++)leaves[i]=(TCWatchListRect){300,400+i*2,1,1};
assert(TCWatchListSelectTouch(&p,rows,24,leaves,512,&out,&mode)==0&&mode==1);
assert(out.start.y==97&&out.end.y==65);
''')

    def test_adaptive_live_failure_cannot_reselect_and_stale_gate_still_executes(self):
        self.execute('''
TCWatchListDrag p={{0,47.5,162,149.5},{81,138.25},{81,106.25},1},out={0};int mode=7;
TCWatchListRect row={2,73.5,158,47};
assert(TCWatchListSelectTouch(&p,&row,1,&row,1,&out,&mode)==0&&mode==1);
for(int gate=0;gate<4;gate++) {
 assert(!TCWatchListTouchAnchorReady(&out,row,row,gate==0?0:1,gate==1?0:1,gate==2?0:1,gate==3?0:1));
}
assert(!TCWatchListTouchAnchorReady(&out,row,row,2,1,1,1));
for(int component=0;component<4;component++) {
 TCWatchListRect stale=row;
 switch(component){case 0:stale.x+=.5;break;case 1:stale.y+=.5;break;case 2:stale.width-=.5;break;case 3:stale.height-=.5;break;}
 assert(!TCWatchListTouchAnchorReady(&out,row,stale,1,1,1,1));
}
assert(out.start.y==97&&out.end.y==65&&mode==1);
''')
        source = (ROOT / 'TouchColorWatchUITests/WatchWorkflowTests.swift').read_text()
        helper = source.split('private func reachSavedColorByTouch(', 1)[1].split('    @MainActor func testEditSavedCopy', 1)[0]
        self.assertEqual(helper.count('TCWatchListSelectTouch('), 1)
        self.assertEqual(helper.count('guard anchorReady() else'), 2)
        self.assertNotIn('continue', helper)
        self.assertNotIn('while', helper.split('let anchorIndex =', 1)[1])
        final_gate = helper.rindex('guard anchorReady() else')
        self.assertGreater(final_gate, helper.index('XCTAssertEqual(end.screenPoint'))
        self.assertLess(final_gate, helper.index('diagnostic("PLAN"'))
        self.assertLess(helper.index('diagnostic("PLAN"'), helper.index('start.press('))

    def test_adaptive_current_target_and_live_leaf_checks_are_in_final_gate(self):
        source = (ROOT / 'TouchColorWatchUITests/WatchWorkflowTests.swift').read_text()
        helper = source.split('private func reachSavedColorByTouch(', 1)[1].split('    @MainActor func testEditSavedCopy', 1)[0]
        for required in ('list.descendants(matching: .any).matching(identifier: identifier)',
                         'let matches = targetQuery.count',
                         'guard let capturedTarget = targetFrame else { return matches == 0 }',
                         'guard matches == 1 else { return false }', 'targetQuery.element',
                         'target.exists', 'target.identifier == identifier', 'target.elementType == .button',
                         'target.frame == capturedTarget', 'anchor.children(matching: .any).count == 0',
                         'guard currentHome(), currentTarget() else { return false }'):
            self.assertIn(required, helper)
        ready = helper.split('if decision == TCWatchListReady {', 1)[1].split('guard decision ==', 1)[0]
        self.assertIn('guard currentHome(), currentTarget() else {', ready)
        self.assertLess(ready.index('currentTarget()'), ready.index('button.tap()'))
        self.assertEqual(helper.count('app.snapshot()'), 1)
        self.assertIn('for attempt in 0...12', helper)
        self.assertIn('guard attempt < 12', helper)
        self.assertEqual(helper.count('start.press('), 1)
        self.assertIn('start.press(forDuration: 0.01, thenDragTo: end, withVelocity: .slow, thenHoldForDuration: 0.15)', helper)

    def test_adaptive_diagnostics_reuse_fields_and_preserve_all_legacy_geometry(self):
        import hashlib
        source = (ROOT / 'TouchColorWatchUITests/WatchWorkflowTests.swift').read_text()
        helper = source.split('private func reachSavedColorByTouch(', 1)[1].split('    @MainActor func testEditSavedCopy', 1)[0]
        diagnostic = helper.split('func diagnostic(', 1)[1].split('func failAnchor(', 1)[0]
        for forbidden in ('app.', 'list.', 'anchorQuery', 'targetQuery', 'isHittable', '.snapshot()', '.screenshot()'):
            self.assertNotIn(forbidden, diagnostic)
        for required in ('originalStart=', 'originalEnd=', 'targetFrame=', 'mode=', 'anchor=',
                         'rows=', 'live=', 'validationMilliseconds=', 'diagnostic.prefix(4096)'):
            self.assertIn(required, diagnostic)
        self.assertEqual(helper.count('diagnostic("PLAN"'), 1)
        self.assertEqual(helper.count('diagnostic("REJECT"'), 1)
        self.assertIn('ProcessInfo.processInfo.systemUptime', helper)
        # Twenty-four ordinary maximum-length canonical identifiers and concrete
        # screen frames fit in one capped record; exotic strings still truncate.
        rows = ';'.join(f'watch.color.{2147483647-i}=(211.5, 257.5, 207.5, 59.5)' for i in range(24))
        self.assertLess(len(rows) + 1000, 4096)
        header = HEADER.read_text()
        legacy = header.split('/* Gap-only adaptation.', 1)[0] + '#endif\n'
        self.assertEqual(hashlib.sha256(legacy.encode()).hexdigest(),
                         '3bcf62a7371e4b7c1447f16f263baba0dca61cdf69e08484e0efd3205b28ba88')
        adapter = header.split('static inline int TCWatchListSelectTouch(', 1)[1]
        self.assertIn('const TCWatchListDrag *original', header)
        self.assertNotRegex(adapter, r'original->\w+(?:\.\w+)?\s*=(?!=)')
        self.assertIn('candidate.end.y - candidate.start.y != delta', adapter)
        self.assertIn('if (selected < 0 || tied) return -1;', adapter)



    def test_partial_target_retained_color_row_is_action_geometry_only(self):
        f = json.loads((ROOT / 'TouchColorWatchUITests/Fixtures/home-list-a6558c-partial-target.json').read_text())
        self.assertEqual(f['source'], 'a6558c8ffa1cf86b499bcfa00f02f8d7bcb1de2b')
        self.assertEqual((f['run'], f['job'], f['artifact']), (37338286671, 111860840406, 11359060869))
        self.assertEqual(f['target_identifier'], 'watch.color.1')
        self.assertIn('target=watch.color.1', f['last_plan_line'])
        self.assertIn("identifier: 'watch.color.1'", f['failure_target_line'])
        self.assertEqual(f['last_logged_plan_target'], [2,157,158,44])
        self.assertEqual(f['failure_ax_target'], [2,155,158,44])
        self.assertIsNone(f['actual_target_hittability']); self.assertIsNone(f['actual_tap_delivery'])
        self.assertEqual(f['gesture_dispatches_observed'], 12)
        self.execute("""
TCWatchListRect content={0,47.5,162,149.5};TCWatchListPoint p={0};
TCWatchListRect last={2,157,158,44},final={2,155,158,44};
assert(!TCWatchListContains(content,last)&&!TCWatchListContains(content,final));
assert(TCWatchListPartialTapPoint(content,last,&p)&&p.x==81&&p.y==179);
assert(TCWatchListPartialTapPoint(content,final,&p)&&p.x==81&&p.y==177);
/* Historical hittability is unknown. Only synthetic true/false exercises gates. */
assert(!TCWatchListPartialTapReady(content,final,final,&final,1,1,1,0,1,p));
assert(TCWatchListPartialTapReady(content,final,final,&final,1,1,1,1,1,p));
""")

    def test_partial_target_clipping_center_and_horizontal_negatives(self):
        self.execute("""
TCWatchListRect c={0,47.5,162,149.5};TCWatchListPoint p={-1,-1};
TCWatchListRect good={2,155,158,44};assert(TCWatchListPartialTapPoint(c,good,&p));
TCWatchListRect bad[]={{2,176,158,44},{2,190,158,44},{2,20,158,44},
 {2,40,158,44},{-1,155,158,44},{2,155,161,44},{2,100,158,44},
 {2,196,158,1},{2,48,158,200},{NAN,155,158,44},{2,155,0,44},{2,155,158,-1}};
for(size_t i=0;i<sizeof(bad)/sizeof(*bad);i++) {
 p=(TCWatchListPoint){-1,-1};assert(!TCWatchListPartialTapPoint(c,bad[i],&p));
 assert(p.x==-1&&p.y==-1);
}
assert(!TCWatchListPartialTapPoint(c,good,NULL));
assert(!TCWatchListPartialTapPoint((TCWatchListRect){0,0,0,0},good,&p));
/* Exact4pt/10% boundary is closed; no arbitrary floating tolerance. */
good=(TCWatchListRect){2,157,158,44};assert(TCWatchListPartialTapPoint(c,good,&p));
good.y=nextafter(good.y,INFINITY);assert(!TCWatchListPartialTapPoint(c,good,&p));
good=(TCWatchListRect){2,179,158,20};assert(TCWatchListPartialTapPoint(c,good,&p));
good.y=nextafter(good.y,INFINITY);assert(!TCWatchListPartialTapPoint(c,good,&p));
""")

    def test_partial_target_semantic_overlay_duplicate_and_missing_center_fail(self):
        self.execute("""
TCWatchListRect c={0,47.5,162,149.5},target={2,155,158,44};TCWatchListPoint p;
assert(TCWatchListPartialTapPoint(c,target,&p));
TCWatchListRect leaves[]={target,{70,170,20,20}};
assert(!TCWatchListPartialTapReady(c,target,target,leaves,2,1,1,1,1,p));
leaves[1]=target;assert(!TCWatchListPartialTapReady(c,target,target,leaves,2,1,1,1,1,p));
leaves[1]=(TCWatchListRect){81,177,2,2};
assert(!TCWatchListPartialTapReady(c,target,target,leaves,2,1,1,1,1,p));
leaves[0]=(TCWatchListRect){2,100,158,44};
assert(!TCWatchListPartialTapReady(c,target,target,leaves,1,1,1,1,1,p));
leaves[0]=target;leaves[1]=(TCWatchListRect){NAN,0,1,1};
assert(!TCWatchListPartialTapReady(c,target,target,leaves,2,1,1,1,1,p));
assert(!TCWatchListPartialTapReady(c,target,target,NULL,1,1,1,1,1,p));
assert(!TCWatchListPartialTapReady(c,target,target,&target,0,1,1,1,1,p));
assert(!TCWatchListPartialTapReady(c,target,target,&target,513,1,1,1,1,p));
""")

    def test_partial_target_live_identity_hittability_home_and_exact_point_required(self):
        self.execute("""
TCWatchListRect c={0,47.5,162,149.5},target={2,155,158,44};TCWatchListPoint p;
assert(TCWatchListPartialTapPoint(c,target,&p));
for(int gate=0;gate<4;gate++)assert(!TCWatchListPartialTapReady(c,target,target,&target,1,
 gate==0?0:1,gate==1?0:1,gate==2?0:1,gate==3?0:1,p));
assert(!TCWatchListPartialTapReady(c,target,target,&target,1,2,1,1,1,p));
for(int gate=0;gate<3;gate++)assert(!TCWatchListPartialTapReady(c,target,target,&target,1,
 1,gate==0?2:1,gate==1?2:1,gate==2?2:1,p));
for(int n=0;n<4;n++){
 TCWatchListRect live=target;
 switch(n){case 0:live.x+=.5;break;case 1:live.y+=.5;break;case 2:live.width-=.5;break;case 3:live.height-=.5;break;}
 assert(!TCWatchListPartialTapReady(c,target,live,&target,1,1,1,1,1,p));
}
TCWatchListPoint wrong[]={{81,177.5},{80.5,177},{NAN,177},{81,INFINITY},{81,197},{81,47.5}};
for(size_t i=0;i<sizeof(wrong)/sizeof(*wrong);i++)
 assert(!TCWatchListPartialTapReady(c,target,target,&target,1,1,1,1,1,wrong[i]));
""")

    def test_partial_target_does_not_rewrite_planner_or_non_tap_observation(self):
        self.execute("""
TCWatchListRect v={0,0,162,197},nav={0,0,162,47.5},target={2,155,158,44};
TCWatchListDrag p={0};TCWatchListPoint point;
assert(TCWatchListPlan(v,v,nav,1,1,target,NULL,0,&p)==TCWatchListLater);
assert(p.start.y-p.end.y==12);
TCWatchListDrag before=p;
assert(TCWatchListPartialTapPoint(p.content,target,&point));
assert(p.start.y==before.start.y&&p.end.y==before.end.y&&p.direction==before.direction);
assert(!TCWatchListContains(p.content,target));
""")
        source=(ROOT/'TouchColorWatchUITests/WatchWorkflowTests.swift').read_text()
        helper=source.split('private func reachSavedColorByTouch(',1)[1].split('    @MainActor func testEditSavedCopy',1)[0]
        partial=helper.split('// Action-only partial target:',1)[1].split('            if decision == TCWatchListReady',1)[0]
        self.assertIn('if tap, decision == TCWatchListEarlier || decision == TCWatchListLater',partial)
        self.assertEqual(partial.count('coordinate.tap()'),1)
        self.assertEqual(partial.count('guard partialTargetReady('),2)
        self.assertIn('let matches = app.buttons.matching(identifier: identifier).count',partial)
        self.assertIn('guard matches == 1',partial)
        self.assertIn('button.children(matching: .any).count == 0',partial)
        self.assertIn('guard currentHome(), currentTarget()',partial)
        self.assertIn('covering.count == 1',partial)
        self.assertIn('button.isHittable, liveFrame = button.frame',partial)
        self.assertIn('CGVector(dx: 0.5, dy: 0.5)',partial)
        self.assertLess(partial.index('let screenPoint = coordinate.screenPoint'),partial.index('guard partialTargetReady(actualPoint)'))
        self.assertLess(partial.index('guard partialTargetReady(actualPoint)'),partial.index('coordinate.tap()'))
        self.assertIn('TCWatchListContains(plan.content, rect(button.frame))',helper)
        self.assertIn('reachSavedColorByTouch("watch.color.1", tap: false)',source)
        self.assertEqual(helper.count('app.snapshot()'),1)
        self.assertEqual(helper.count('start.press('),1)
        self.assertIn('for attempt in 0...12',helper);self.assertIn('guard attempt < 12',helper)

if __name__ == '__main__':
    unittest.main()
