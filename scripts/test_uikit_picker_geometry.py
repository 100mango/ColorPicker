"""Run the actual test-helper classifier/geometry against retained XCTest data.

A minimal C shim supplies CoreGraphics rectangle arithmetic on non-Apple hosts;
this is not an Apple snapshot or simulator claim. Hosted XCTest replays the same
fixture against the real frameworks in TCAdaptiveLayoutTests.
"""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'ColorPickerTests/Fixtures/photos-ipad-large-7e3-hierarchy.json'
KINDS = {'Popover': 'TCPickerNodePopover', 'NavigationBar': 'TCPickerNodeNavigationBar', 'ScrollView': 'TCPickerNodeScrollView'}
CG_SHIM = r'''
#include <math.h>
typedef struct { double x,y; } CGPoint;
typedef struct { double width,height; } CGSize;
typedef struct { CGPoint origin; CGSize size; } CGRect;
#define CGRectNull ((CGRect){{INFINITY,INFINITY},{0,0}})
static inline CGRect CGRectMake(double x,double y,double w,double h){return (CGRect){{x,y},{w,h}};}
static inline CGPoint CGPointMake(double x,double y){return (CGPoint){x,y};}
static inline int CGRectIsNull(CGRect r){return isinf(r.origin.x)&&isinf(r.origin.y);}
static inline int CGRectIsEmpty(CGRect r){return r.size.width<=0||r.size.height<=0;}
static inline int CGRectEqualToRect(CGRect a,CGRect b){return a.origin.x==b.origin.x&&a.origin.y==b.origin.y&&a.size.width==b.size.width&&a.size.height==b.size.height;}
static inline double CGRectGetMinX(CGRect r){return r.origin.x;}
static inline double CGRectGetMinY(CGRect r){return r.origin.y;}
static inline double CGRectGetMaxX(CGRect r){return r.origin.x+r.size.width;}
static inline double CGRectGetMaxY(CGRect r){return r.origin.y+r.size.height;}
static inline double CGRectGetMidX(CGRect r){return r.origin.x+r.size.width/2;}
static inline double CGRectGetMidY(CGRect r){return r.origin.y+r.size.height/2;}
static inline double CGRectGetWidth(CGRect r){return r.size.width;}
static inline double CGRectGetHeight(CGRect r){return r.size.height;}
static inline CGRect CGRectInset(CGRect r,double x,double y){return CGRectMake(r.origin.x+x,r.origin.y+y,r.size.width-2*x,r.size.height-2*y);}
static inline int CGRectContainsPoint(CGRect r,CGPoint p){return p.x>=r.origin.x&&p.y>=r.origin.y&&p.x<CGRectGetMaxX(r)&&p.y<CGRectGetMaxY(r);}
static inline int CGRectIntersectsRect(CGRect a,CGRect b){return CGRectGetMaxX(a)>b.origin.x&&CGRectGetMaxX(b)>a.origin.x&&CGRectGetMaxY(a)>b.origin.y&&CGRectGetMaxY(b)>a.origin.y;}
static inline CGRect CGRectIntersection(CGRect a,CGRect b){double x=fmax(a.origin.x,b.origin.x),y=fmax(a.origin.y,b.origin.y),w=fmin(CGRectGetMaxX(a),CGRectGetMaxX(b))-x,h=fmin(CGRectGetMaxY(a),CGRectGetMaxY(b))-y;return w>0&&h>0?CGRectMake(x,y,w,h):CGRectNull;}
static inline CGRect CGRectUnion(CGRect a,CGRect b){if(CGRectIsNull(a))return b;if(CGRectIsNull(b))return a;double x=fmin(a.origin.x,b.origin.x),y=fmin(a.origin.y,b.origin.y);return CGRectMake(x,y,fmax(CGRectGetMaxX(a),CGRectGetMaxX(b))-x,fmax(CGRectGetMaxY(a),CGRectGetMaxY(b))-y);}
'''


class UIKitPickerGeometryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compiler = shutil.which('cc')
        if not cls.compiler:
            raise RuntimeError('A C compiler is required for the actual helper regression; do not skip this prerequisite')
        cls.temporary = tempfile.TemporaryDirectory(prefix='touchcolor-picker-regression-')
        cls.directory = Path(cls.temporary.name)
        (cls.directory / 'Foundation').mkdir()
        (cls.directory / 'CoreGraphics').mkdir()
        (cls.directory / 'Foundation/Foundation.h').write_text('typedef int BOOL; typedef unsigned long NSUInteger;\n#define YES 1\n#define NO 0\n#define MAX(a,b) ((a)>(b)?(a):(b))\n')
        (cls.directory / 'CoreGraphics/CoreGraphics.h').write_text(CG_SHIM)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def run_helper(self, body):
        source = self.directory / 'test.c'
        header = ROOT / 'TouchColorUITests/TCSystemPickerGeometry.h'
        routes = ROOT / 'TouchColorUITests/TCFilesPickerRoute.h'
        source.write_text(f'#include "{header}"\n#include "{routes}"\n#include <assert.h>\n#include <stddef.h>\nint main(void){{\n{body}\nreturn 0;\n}}\n')
        program = self.directory / 'test'
        compiled = subprocess.run([self.compiler, '-std=gnu11', '-Wno-deprecated', '-Wall', '-Wextra', '-Werror', '-I'+str(self.directory), str(source), '-lm', '-o', str(program)], capture_output=True, text=True, timeout=15)
        self.assertEqual(compiled.returncode, 0, compiled.stderr[:4000])
        executed = subprocess.run([str(program)], capture_output=True, text=True, timeout=5)
        self.assertEqual(executed.returncode, 0, executed.stderr[:4000])

    def retained_popover_nodes(self):
        data = json.loads(FIXTURE.read_text())
        self.assertEqual(data['source']['job'], 111448839083)
        self.assertIn('not the unrecorded', data['source']['kind'])
        nodes = data['nodes']
        self.assertEqual(len(nodes), 256)
        root = next(index for index, node in enumerate(nodes) if node['type'] == 'Popover')
        selected = []
        for index, node in enumerate(nodes):
            ancestor = index
            while ancestor >= 0 and ancestor != root:
                parent = nodes[ancestor]['parent']
                self.assertLess(parent, ancestor, 'The retained hierarchy must be acyclic')
                ancestor = parent
            if ancestor >= 0:
                selected.append((index == root, node))
        self.assertEqual(len(selected), 167)
        return selected

    def test_retained_real_tree_and_label_only_variant(self):
        nodes = self.retained_popover_nodes()
        for label_only in (False, True):
            statements = ['TCPickerSnapshotObservation o={CGRectNull,0,0,NO};']
            for root, node in nodes:
                identifier, label = node['identifier'], node['label']
                if label_only and identifier == 'Photos':
                    identifier, label = '', 'Photos'
                frame = ','.join(str(v) for v in node['frame'])
                statements.append(f'TCObservePhotosSnapshotNode(&o,{KINDS.get(node["type"], "TCPickerNodeOther")},{json.dumps(identifier)},{json.dumps(label)},CGRectMake({frame}),{int(root)});')
            statements.append('assert(o.nodes==167);assert(o.chromeMatches==2);assert(o.bounds.origin.x==364);assert(o.bounds.origin.y==372);assert(o.bounds.size.width==833);assert(o.bounds.size.height==640);')
            statements.append('CGPoint p;assert(TCPickerDismissalPoint(CGRectMake(0,0,1376,1032),o.bounds,&p));assert(p.x==186);assert(p.y==516);')
            self.run_helper('\n'.join(statements))

    def test_bound_root_survives_missing_remote_children_without_accepting_arbitrary_window(self):
        self.run_helper('''
TCPickerSnapshotObservation root={CGRectNull,0,0,NO}, unrelated={CGRectNull,0,0,NO}, empty={CGRectNull,0,0,NO};
TCObservePhotosSnapshotNode(&root,TCPickerNodeOther,"","",CGRectMake(364,372,833,640),YES);
assert(root.bounds.size.width==833);assert(root.chromeMatches==0);
TCObservePhotosSnapshotNode(&unrelated,TCPickerNodeOther,"","Photos",CGRectMake(0,0,1376,1032),NO);
assert(CGRectIsNull(unrelated.bounds));
TCObservePhotosSnapshotNode(&empty,TCPickerNodeOther,"","",CGRectMake(0,0,0,0),YES);
assert(CGRectIsNull(empty.bounds));
''')

    def test_invalid_actual_popover_root_rejects_valid_photos_child(self):
        self.run_helper('''
TCPickerSnapshotObservation invalid={CGRectNull,0,0,NO};
TCObservePhotosSnapshotNode(&invalid,TCPickerNodePopover,"","",CGRectMake(NAN,0,0,0),YES);
TCObservePhotosSnapshotNode(&invalid,TCPickerNodeNavigationBar,"Photos","",CGRectMake(380,120,600,62),NO);
assert(!invalid.rootUsable);assert(CGRectIsNull(invalid.bounds));
CGPoint p;assert(!TCPickerDismissalPoint(CGRectMake(0,0,1376,1032),invalid.bounds,&p));
''')

    def test_missing_and_invalid_polls_reset_both_stability_rectangles(self):
        self.run_helper('''
TCPickerSnapshotObservation good={CGRectNull,0,0,NO}, invalid={CGRectNull,0,0,NO};
TCObservePhotosSnapshotNode(&good,TCPickerNodePopover,"","",CGRectMake(364,372,833,640),YES);
TCObservePhotosSnapshotNode(&invalid,TCPickerNodePopover,"","",CGRectMake(NAN,0,0,0),YES);
TCObservePhotosSnapshotNode(&invalid,TCPickerNodeNavigationBar,"Photos","",CGRectMake(380,120,600,62),NO);
for(int missing=0;missing<2;missing++){
 CGRect previous=CGRectNull,observed=CGRectNull;
 assert(!TCPickerAdvanceStability(&good,&previous,&observed));
 assert(!TCPickerAdvanceStability(missing?NULL:&invalid,&previous,&observed));
 assert(CGRectIsNull(previous));assert(CGRectIsNull(observed));
 assert(!TCPickerAdvanceStability(&good,&previous,&observed));
 assert(TCPickerAdvanceStability(&good,&previous,&observed));
 assert(!TCPickerAdvanceStability(missing?NULL:&invalid,&previous,&observed));
 assert(CGRectIsNull(previous));assert(CGRectIsNull(observed));
}
''')

    def test_chrome_classifier_matches_only_observed_types_and_names(self):
        self.run_helper('''
assert(TCPhotosSnapshotNodeIsChrome(TCPickerNodeNavigationBar,"Photos",""));
assert(TCPhotosSnapshotNodeIsChrome(TCPickerNodeNavigationBar,"","Photos"));
assert(TCPhotosSnapshotNodeIsChrome(TCPickerNodeScrollView,"photosView_content_scroll_view",""));
assert(!TCPhotosSnapshotNodeIsChrome(TCPickerNodeOther,"Photos","Photos"));
assert(!TCPhotosSnapshotNodeIsChrome(TCPickerNodeNavigationBar,"Color Canvas","Color Canvas"));
assert(!TCPhotosSnapshotNodeIsChrome(TCPickerNodeNavigationBar,NULL,NULL));
''')

    def test_actual_phone_files_trees_classify_provider_state_without_title_actions(self):
        fixture = json.loads((ROOT / 'TouchColorUITests/Fixtures/files-iphone-7e3-hierarchies.json').read_text())
        self.assertEqual([case['job'] for case in fixture['cases']], [111448839064, 111448839139])
        kinds = {'Other': 'TCFilesNodeOther', 'Cell': 'TCFilesNodeCell', 'Button': 'TCFilesNodeButton', 'StaticText': 'TCFilesNodeStaticText'}
        for case, count in zip(fixture['cases'], (151, 154)):
            nodes = case['nodes']
            self.assertEqual(len(nodes), count)
            statements = ['unsigned providers=0,locations=0,titles=0;']
            folder = next(node for node in nodes if node['identifier']=='Palette Fixtures, Container')
            ancestor = folder['parent']
            while ancestor >= 0 and nodes[ancestor]['identifier']!='File View':
                parent = nodes[ancestor]['parent']
                self.assertLess(parent, ancestor)
                ancestor = parent
            self.assertGreaterEqual(ancestor, 0, 'The real fixture folder is already in the local provider File View')
            for node in nodes:
                kind = kinds.get(node['type'], '(TCFilesNodeKind)99')
                identifier, label = json.dumps(node['identifier']), json.dumps(node['label'])
                statements.append(f'{{TCFilesRoute r=TCClassifyFilesRoute({kind},{identifier},{label},"On My iPhone");providers+=(r==TCFilesRouteLocalProvider);locations+=(r==TCFilesRouteLocationCell);')
                if node['type']=='StaticText' and node['label']=='On My iPhone':
                    parent = nodes[node['parent']]
                    self.assertEqual(parent['type'], 'NavigationBar')
                    self.assertEqual(parent['identifier'], 'FullDocumentManagerViewControllerNavigationBar')
                    statements.append('assert(r==TCFilesRouteNone);titles++;')
                statements.append('}')
            statements.append('assert(providers==1);assert(locations==0);assert(titles==1);')
            self.run_helper('\n'.join(statements))

    def test_files_location_actions_require_cells_and_provider_identity_is_exact(self):
        self.run_helper('''
assert(TCClassifyFilesRoute(TCFilesNodeCell,"DOC.sidebar.item.On My iPad","On My iPad","On My iPad")==TCFilesRouteLocationCell);
assert(TCClassifyFilesRoute(TCFilesNodeCell,"","On My iPhone","On My iPhone")==TCFilesRouteLocationCell);
assert(TCClassifyFilesRoute(TCFilesNodeStaticText,"","On My iPhone","On My iPhone")==TCFilesRouteNone);
assert(TCClassifyFilesRoute(TCFilesNodeButton,"","Browse","On My iPhone")==TCFilesRouteBrowse);
assert(TCClassifyFilesRoute(TCFilesNodeOther,"DOC.browsingRoot Source: com.apple.FileProvider.LocalStorage, Title: On My iPhone","","On My iPhone")==TCFilesRouteLocalProvider);
assert(TCClassifyFilesRoute(TCFilesNodeOther,"DOC.browsingRoot Source: com.apple.FileProvider.LocalStorage, Title: Palette Fixtures","","On My iPhone")==TCFilesRouteNone);
assert(TCClassifyFilesRoute(TCFilesNodeOther,"DOC.browsingRoot Source: com.apple.FileProvider.CloudDocs, Title: On My iPhone","","On My iPhone")==TCFilesRouteNone);
assert(TCClassifyFilesRoute(TCFilesNodeStaticText,"","TouchColor-Ordered-Colors.json","On My iPhone")==TCFilesRouteFixtureFile);
''')

    def test_geometry_rejects_invalid_or_unsafe_regions(self):
        self.run_helper('''
CGRect w=CGRectMake(0,0,375,514);CGPoint p;
CGRect bad[]={w,CGRectInset(w,10,10),CGRectMake(0,0,0,0),CGRectNull,CGRectMake(NAN,0,100,100),CGRectMake(400,0,100,100),CGRectMake(100,50,-100,100)};
for(int i=0;i<7;i++)assert(!TCPickerDismissalPoint(w,bad[i],&p));
assert(!TCPickerDismissalPoint(w,CGRectMake(100,50,200,300),NULL));
for(int x=-40;x<400;x+=20)for(int y=-40;y<550;y+=20)for(int width=20;width<400;width+=40){CGRect r=CGRectMake(x,y,width,200);if(TCPickerDismissalPoint(w,r,&p)){assert(CGRectContainsPoint(CGRectInset(w,20,20),p));assert(!CGRectContainsPoint(CGRectInset(r,-12,-12),p));}}
''')


if __name__ == '__main__':
    unittest.main()
