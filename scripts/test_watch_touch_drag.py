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
                         'TCWatchListTouchAnchorIndex(&plan, $0.baseAddress, $0.count)',
                         'guard anchorIndex >= 0', 'coveringLeaves.count == 1',
                         'coveringLeaves[0].id == captured.id', 'coveringLeaves[0].type == captured.type',
                         'coveringLeaves[0].frame == captured.frame',
                         'list.descendants(matching: .any).matching(identifier: captured.id)',
                         'guard anchorQuery.count == 1', 'let anchor = anchorQuery.element',
                         'anchor.exists', 'anchor.identifier == captured.id', 'anchor.elementType == captured.type',
                         'anchor.isHittable', 'liveFrame = anchor.frame',
                         'app.navigationBars.count == 1', 'app.navigationBars["TouchColor"].exists',
                         '!app.buttons["BackButton"].exists', 'app.alerts.count == 0', 'app.sheets.count == 0',
                         'guard currentHome() else { return false }',
                         'TCWatchListTouchAnchorReady(&plan, rect(captured.frame), rect(liveFrame)',
                         'WATCH_TOUCH_ANCHOR_REJECT', 'diagnostic.prefix(4096)', 'live=\\(liveAnchorState)'):
            self.assertIn(expected, helper)
        self.assertEqual(helper.count('guard anchorReady() else'), 2)
        self.assertLess(helper.rindex('guard anchorReady() else'), helper.index('start.press('))
        self.assertGreater(helper.rindex('guard anchorReady() else'), helper.index('XCTAssertEqual(end.screenPoint'))
        self.assertEqual(helper.count('app.snapshot()'), 1)
        for forbidden in ('XCTAssertTrue(list.isHittable)', '.firstMatch', 'anchor.tap()', 'anchor.press(',
                          'hitPoint', 'value(forKey:', 'perform(', 'plan.start =', 'plan.end ='):
            self.assertNotIn(forbidden, helper)
        # Unknown semantic leaves can reject an overlap, never become a fallback.
        self.assertIn('semanticLeaves.filter { TCWatchListPointInside(rect($0.frame), plan.start) != 0 }', helper)
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


if __name__ == '__main__':
    unittest.main()
