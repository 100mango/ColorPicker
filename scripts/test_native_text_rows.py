"""Portable closed-row and phase-isolation checks; no native acceptance claim."""
import copy
import os
from pathlib import Path
import re
import unittest
from unittest.mock import patch
import native_text_rows as rows
from native_content_size import VISION_CASES as LARGEST_CASES, WATCH_CASES
from vision_suites import CASES

ROOT = Path(__file__).resolve().parents[1]
SHA = 'a' * 40


def environment(binding):
    return {'GITHUB_SHA': binding['source_sha'], 'TOUCHCOLOR_JOB_PLATFORM': binding['platform'],
            'TOUCHCOLOR_JOB_MINUTES': str(binding['minutes']), 'TOUCHCOLOR_JOB_LANE': binding['lane'],
            'TOUCHCOLOR_TEXT_PHASE': binding['phase'], 'TOUCHCOLOR_VISION_CASE': binding['case'],
            'TOUCHCOLOR_WATCH_PROFILE': binding['profile'], 'TOUCHCOLOR_EVIDENCE_LIMIT': str(binding['evidence_bytes'])}


class NativeTextRowTests(unittest.TestCase):
    def bindings(self):
        return ([rows.row('vision','normal',case,'',SHA) for case in CASES]
                + [rows.row('vision','system-largest',case,'',SHA) for case in LARGEST_CASES]
                + [rows.row('watch',phase,'',profile,SHA) for phase in rows.PHASES for profile in rows.PROFILES])

    def test_closed_existing_scope_and_exact_row_bindings(self):
        self.assertEqual(rows.LARGEST_VISION_CASES, tuple(LARGEST_CASES))
        self.assertEqual(len(WATCH_CASES), 3)
        self.assertEqual(len(self.bindings()), 15)
        for binding in self.bindings():
            self.assertEqual(rows.validate(binding), binding)
            self.assertEqual(rows.from_environment(binding['platform'],SHA,environment(binding)),binding)
            self.assertEqual(rows.report_binding({'sha':SHA,'native_text_row':binding},environment(binding)),binding)

    def test_malformed_phase_case_profile_platform_source_or_budget_fails(self):
        valid=rows.row('vision','normal','chinese','',SHA)
        for key, value in [('platform','tv'),('phase','largest'),('case','unknown'),('profile','largest'),
                           ('source_sha','z'*40),('lane','vision-chinese-system-largest'),('minutes',45),
                           ('evidence_bytes',700000),('schema',True),('minutes',25.0)]:
            changed=dict(valid);changed[key]=value
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):rows.validate(changed)
        with self.assertRaises(ValueError):rows.row('vision','system-largest','photos','',SHA)
        with self.assertRaises(ValueError):rows.row('watch','normal','chinese','smallest',SHA)
        with self.assertRaises(ValueError):rows.row('watch','normal','','medium',SHA)
        with self.assertRaises(ValueError):rows.validate(dict(valid,extra='not permitted'))

    def test_every_environment_dimension_is_authoritative(self):
        for binding in self.bindings():
            original=environment(binding)
            for key in original:
                env=dict(original);env[key]='foreign'
                with self.subTest(lane=binding['lane'],key=key),self.assertRaises(ValueError):
                    rows.from_environment(binding['platform'],SHA,env)
            changed=dict(binding,source_sha='b'*40)
            with self.assertRaises(ValueError):rows.report_binding({'sha':SHA,'native_text_row':changed},{})
            with self.assertRaises(ValueError):rows.report_binding({'native_text_row':binding},{})

    def test_normal_case_profile_or_source_cannot_satisfy_largest_row(self):
        for platform,case,profile in [('vision','chinese',''),('vision','canvas-audit',''),('watch','','smallest'),('watch','','largest')]:
            largest=rows.row(platform,'system-largest',case,profile,SHA)
            normal=rows.row(platform,'normal',case,profile,SHA)
            with self.assertRaises(ValueError):rows.report_binding({'sha':SHA,'native_text_row':normal},environment(largest))
            if platform=='vision':
                self.assertEqual(rows.vision_roles(largest),['hosted','largest'])
                self.assertEqual(rows.vision_roles(normal),['hosted','normal'])

    def test_matrix_has_exact_19_rows_20mb_and_585_minutes_without_concurrency_change(self):
        source=(ROOT/'.github/workflows/apple-platforms.yml').read_text().split('  native-platform:',1)[1]
        parsed=[]
        for platform,body in re.findall(r'- platform: (\w+)(.*?)(?=\n          - platform:|\n    runs-on:)',source,re.S):
            fields=dict(re.findall(r'^            (\w+): ([\w-]+)$',body,re.M));fields['platform']=platform;parsed.append(fields)
        self.assertEqual(len(parsed),19)
        self.assertEqual(sum(int(row['minutes']) for row in parsed),585)
        self.assertEqual(sum(int(row['evidence_bytes']) for row in parsed),20_000_000)
        self.assertEqual(len({row.get('lane',row['platform']) for row in parsed}),19)
        expected={row['lane']:row for row in self.bindings()}
        for actual in parsed:
            if actual['platform'] not in ('vision','watch'):continue
            binding=expected.pop(actual['lane'])
            self.assertEqual(actual['text_phase'],binding['phase'])
            self.assertEqual(actual.get('vision_case',''),binding['case'])
            self.assertEqual(actual.get('watch_profile',''),binding['profile'])
            self.assertEqual(int(actual['evidence_bytes']),binding['evidence_bytes'])
            self.assertEqual(int(actual['minutes']),binding['minutes'])
        self.assertFalse(expected)
        self.assertIn('max-parallel: 2',source)
        self.assertIn('fail-fast: false',source)
        self.assertNotIn('max-parallel: 1',source)
        self.assertIn('TOUCHCOLOR_TEXT_PHASE: ${{ matrix.text_phase }}',source)

    def test_exact_evidence_outputs_gate_after_upload_even_on_failure(self):
        workflow=(ROOT/'.github/workflows/apple-platforms.yml').read_text()
        self.assertLess(workflow.index('Retain small test evidence for review'),workflow.index('Require complete exact native text row evidence'))
        self.assertIn('native_text_evidence.py retain build/evidence',workflow)
        self.assertIn("in ('vision','watch'): sys.exit(0)",workflow)
        self.assertIn('native_text_evidence_complete',workflow)


if __name__=='__main__':unittest.main()
