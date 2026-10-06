"""Closed eight-row route; standard-library-only prerequisite checks."""
from pathlib import Path
import re
import unittest

ROOT=Path(__file__).resolve().parents[1]
BRANCH='codex/vision-row-repair'
WORKFLOW='100mango/ColorPicker/.github/workflows/vision-row-repair.yml@refs/heads/'+BRANCH
ROWS=('vision-chinese','vision-canvas-audit','vision-paste-relaunch','vision-png-export',
      'vision-photos','vision-cancel','vision-files-select','vision-chinese-system-largest')


def matrix(text):
    start=text.index('        include:\n')+len('        include:\n')
    end=text.index('    runs-on:',start)
    return start,end,re.findall(r'          - platform:.*?(?=\n          - platform:|\Z)',text[start:end],re.S)

def lane(row):
    match=re.search(r'^            lane: ([^\n]+)',row,re.M)
    return match.group(1) if match else None


class FixedVisionRepairRouteTests(unittest.TestCase):
    def setUp(self):
        self.base=(ROOT/'.github/workflows/apple-platforms.yml').read_text()
        self.text=(ROOT/'.github/workflows/vision-row-repair.yml').read_text()

    def test_exact_push_only_identity_no_selector_inputs(self):
        self.assertEqual(self.text.split('on:\n',1)[1].split('permissions:',1)[0],
                         '  push:\n    branches: ['+BRANCH+']\n')
        self.assertIn('permissions:\n  contents: read\n',self.text)
        self.assertIn('branches: [codex/platform-integration]',self.base)
        self.assertNotIn(BRANCH,(ROOT/'.github/workflows/ios.yml').read_text())
        self.assertIn('group: touchcolor-platforms-refs/heads/codex/platform-integration\n  cancel-in-progress: false',self.text)
        self.assertIn('group: touchcolor-platforms-${{ github.ref }}',self.base)

    def test_exact_failed_eight_rows_not_green_or_other_platforms(self):
        base=matrix(self.base)[2];rows=matrix(self.text)[2]
        self.assertEqual(len(base),19)
        self.assertEqual([lane(r) for r in rows],list(ROWS))
        self.assertEqual([r.rstrip() for r in rows],[r.rstrip() for r in base if lane(r) in ROWS])
        self.assertTrue(all(r.startswith('          - platform: vision\n') and '\n            minutes: 35\n' in r for r in rows))
        for absent in ('vision-json-export','vision-corrupt-audit','vision-canvas-audit-system-largest'):
            self.assertNotIn(absent,[lane(r) for r in rows])
        self.assertIn('      max-parallel: 2\n',self.text)
        self.assertIn('  native-platform:\n    needs: native-prerequisites\n',self.text)

    def test_exact_entire_workflow_except_named_route_changes(self):
        # Inverse route projection must reproduce the complete admitted canonical
        # YAML bytes, including every existing job/step/condition/shell body.
        actual=self.text
        actual=actual.replace('name: Fixed Vision row repair qualification','name: Native Apple platform milestone',1)
        actual=actual.replace('branches: ['+BRANCH+']\n','branches: [codex/platform-integration]\n  workflow_dispatch:\n',1)
        actual=actual.replace('group: touchcolor-platforms-refs/heads/codex/platform-integration','group: touchcolor-platforms-${{ github.ref }}',1)
        guard='          test "$GITHUB_REF" = refs/heads/'+BRANCH+'\n          test "$GITHUB_WORKFLOW_REF" = '+WORKFLOW
        self.assertEqual(actual.count(guard),2)
        actual=actual.replace(guard,'          test "$GITHUB_REF" = refs/heads/codex/platform-integration')
        self.assertEqual(actual.count(' test_vision_repair_route\n'),2)
        actual=actual.replace(' test_vision_repair_route\n','\n')
        start,end,_=matrix(actual);a,b,_=matrix(self.base)
        actual=actual[:start]+self.base[a:b]+actual[end:]
        self.assertEqual(actual,self.base)

    def test_guards_bind_actual_repository_workflow_source(self):
        for name in ('native-prerequisites','native-platform'):
            job=self.text.split('  '+name+':\n',1)[1].split('\n  native-platform:',1)[0]
            for line in ['test "$GITHUB_REPOSITORY" = 100mango/ColorPicker',
                         'test "$GITHUB_REF" = refs/heads/'+BRANCH,
                         'test "$GITHUB_WORKFLOW_REF" = '+WORKFLOW,
                         'test "$GITHUB_WORKFLOW_SHA" = "$GITHUB_SHA"',
                         'test "$(git rev-parse HEAD)" = "$GITHUB_SHA"']:
                self.assertIn(line,job)
            self.assertIn('runs-on: xcode-27',job)
        self.assertNotIn('workflow_dispatch',self.text)
        self.assertNotIn('inputs.',self.text)

    def test_complete_runtime_evidence_and_standard_library_prerequisites(self):
        for name in ['Native visionOS executable and real simulator workflows',
                     'Require every deferred Vision result qualification','Require complete exact native text row evidence',
                     'Validate final evidence byte and path limits','Verify artifact upload reserve']:
            self.assertEqual(self.text.count('- name: '+name+'\n'),1)
        registrations=[x for x in self.text.splitlines() if ' test_vision_repair_route' in x]
        self.assertEqual(len(registrations),2)
        self.assertTrue(all('python3 ' in x and 'unittest -v ' in x for x in registrations))
        # No new Python dependency installation or native tool is introduced.
        self.assertNotIn('pip install',self.text)
        import ast
        source=ast.parse(Path(__file__).read_text())
        imports={node.module if isinstance(node,ast.ImportFrom) else alias.name
                 for node in ast.walk(source) if isinstance(node,(ast.Import,ast.ImportFrom))
                 for alias in (node.names if isinstance(node,ast.Import) else [None])}
        self.assertEqual(imports,{'pathlib','re','unittest','ast'})

if __name__=='__main__':unittest.main()
