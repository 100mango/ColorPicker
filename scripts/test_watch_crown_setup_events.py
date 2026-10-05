"""Versioned event admission adversaries; no Apple semantic-readiness claim."""
import copy
import hashlib
from pathlib import Path
import tempfile
import unittest

from test_watch_crown_result import fixture, stage
import watch_crown_result as result
from watch_crown_setup_events import validate_setup_events, PROTOCOL, BOOT_OUTPUT_LIMIT


class EventProofTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.report = fixture(self.root)
        self.blobs = {x['path']:(self.root/x['path']).read_bytes() for x in self.report['evidence']}
        self.manifest = {x['path']:x for x in self.report['evidence']}
        self.events = self.report['setup_proof']['events']
        self.status_index = self.events[-1]['bootstatus_stage_index']

    def check(self, report=None, blobs=None, manifest=None):
        return validate_setup_events(report or self.report, self.blobs if blobs is None else blobs,
                                     self.manifest if manifest is None else manifest)

    def rejected(self, mutate):
        value = copy.deepcopy(self.report)
        mutate(value)
        with self.assertRaises((ValueError, KeyError, TypeError, AttributeError)):
            self.check(value)
        self.assertFalse(result.validate_result(value, self.root)['complete'])

    def test_complete_events_and_actual_case_receipts_still_required(self):
        self.assertEqual(self.check(), self.events)
        self.assertTrue(result.validate_result(self.report, self.root)['complete'])
        self.rejected(lambda r:r['setup_proof'].update(simultaneous_state='Booted'))

    def test_version_is_exact_and_legacy_is_not_upgraded(self):
        for value in (1, True, 3, None):
            with self.subTest(value=value):self.rejected(lambda r:r.update(schema=value))
        self.rejected(lambda r:r.pop('protocol'))
        self.rejected(lambda r:r.update(protocol='owned-pair-boot-events-v0'))
        self.rejected(lambda r:r.pop('setup_proof'))
        self.rejected(lambda r:r.update(setup_readback=[]))

    def test_uuid_roles_runtime_profile_and_initial_ownership(self):
        changes = [lambda r:r['owned_devices'].reverse(),
            lambda r:r['owned_devices'][0].update(udid=r['owned_devices'][1]['udid']),
            lambda r:r['owned_devices'][0].update(runtime='com.apple.CoreSimulator.SimRuntime.iOS-26-0'),
            lambda r:r['owned_devices'][1].update(deviceTypeIdentifier='Apple-Watch-49mm'),
            lambda r:r['initial_inventory']['devices'][r['owned_devices'][0]['runtime']].append(r['owned_devices'][0]),
            lambda r:r['initial_inventory']['pairs']['pairs'].update({r['pair']['id']:{}})]
        for change in changes:
            with self.subTest(change=change):self.rejected(change)

    def test_pair_and_activation_bindings_cannot_be_invented(self):
        self.rejected(lambda r:r['pair']['record']['watch'].update(udid=r['owned_devices'][0]['udid']))
        self.rejected(lambda r:r['pair']['activation']['record'].update(state='(inactive, disconnected)'))
        self.rejected(lambda r:r['pair']['activation'].update(activation_requested=True))

    def test_activation_branch_is_derived_from_original_state(self):
        for state in ('(inactive, connected)','(inactive, disconnected)','unknown',None):
            with self.subTest(state=state):
                self.rejected(lambda r:r['pair']['record'].update(state=state))
        self.rejected(lambda r:r['pair']['activation'].update(activation_requested=True))

    def test_both_recognized_active_and_inactive_branches_are_valid(self):
        for state in ('(active, connected)','(active, disconnected)'):
            value=copy.deepcopy(self.report);value['pair']['record']['state']=state
            self.assertTrue(result.validate_result(value,self.root)['complete'])
        for state in ('(inactive, connected)','(inactive, disconnected)'):
            value=copy.deepcopy(self.report);value['pair']['record']['state']=state
            value['pair']['activation']['activation_requested']=True
            index=8
            extra=stage(['xcrun','simctl','pair_activate',value['pair']['id']],'setup',42.4,.05,60)
            extra.update(source_sha=value['source']['sha'],budget_phase='work',setup_command_cap_seconds=60,
                         deadline_monotonic=202.4)
            value['stages'].insert(index,extra)
            for event in value['setup_proof']['events']:
                for key in ('boot_stage_index','bootstatus_stage_index'):
                    if event[key]>=index:event[key]+=1
            for case in value['cases']:
                for key in ('stage_index','summary_stage_index','tests_stage_index'):
                    if case[key]>=index:case[key]+=1
                if case['process_cleanup']['inventory_stage_index']>=index:
                    case['process_cleanup']['inventory_stage_index']+=1
            for key in ('device_stage_index','pair_stage_index'):
                if value['cleanup'][key]>=index:value['cleanup'][key]+=1
            self.check(value)
            self.assertTrue(result.validate_result(value,self.root)['complete'])

    def test_every_intervening_command_path_or_wrapper_is_rejected(self):
        for command in (['/usr/bin/xcrun','simctl','shutdown',self.report['device']['udid']],
                        ['xcrun','simctl','shutdown',self.report['device']['udid']],
                        ['/usr/bin/env','xcrun','simctl','shutdown',self.report['device']['udid']],
                        ['sh','-c','xcrun simctl shutdown booted'], ['git','status']):
            with self.subTest(command=command):
                def mutate(r):
                    row=copy.deepcopy(r['stages'][self.status_index]);row['phase']='actual_cold'
                    row['command']=command
                    r['stages'].insert(self.status_index+1,row)
                self.rejected(mutate)

    def test_command_order_aliases_and_repeated_or_missing_readiness(self):
        self.rejected(lambda r:r['stages'][self.status_index]['command'].__setitem__(3,'booted'))
        self.rejected(lambda r:r['stages'][self.status_index]['command'].__setitem__(2,'boot'))
        self.rejected(lambda r:r['stages'].pop(self.status_index))
        self.rejected(lambda r:r['stages'].insert(self.status_index,copy.deepcopy(r['stages'][self.status_index])))
        self.rejected(lambda r:r['stages'][self.status_index-1].update(phase='builds'))

    def test_extra_final_inventory_is_rejected_even_if_it_claims_success(self):
        def extra(r):
            row=copy.deepcopy(r['stages'][self.status_index]);row['command']=['xcrun','simctl','list','devices','available','-j']
            r['stages'].insert(self.status_index+1,row)
        self.rejected(extra)

    def test_prior_failed_inventory_remains_uncertain_under_new_version(self):
        def old(r):
            r['simulator_uncertainty']={'stage_index':self.status_index,'device_commands_forbidden':True}
            r['stages'][self.status_index].update(exit=124,raw_exit=None,timed_out=True)
        self.rejected(old)
        self.rejected(lambda r:r.update(work_stop={'reason':'operation_deadline_expired'}))
        self.rejected(lambda r:r['budget'].update(cleanup_unconfirmed=True))

    def test_nonzero_synthetic_exit_timeout_truncation_or_unconfirmed_cleanup(self):
        for field,value in [('exit',False),('exit',65),('raw_exit',None),('raw_exit',False),
                            ('timed_out',True),('started',False),('stdout_truncated',True),
                            ('process_group_gone',False),('capture_reader_finished',False),
                            ('reader_errors',['failed']),('cleanup_error','failed'),
                            ('reported_device_timeout',True),('simulator_command_completion','unconfirmed')]:
            with self.subTest(field=field):
                self.rejected(lambda r:r['stages'][self.status_index].update({field:value}))

    def test_late_zero_at_or_after_deadline_is_incomplete(self):
        for late in (0,.085142084,.25):
            with self.subTest(late=late):
                def change(r):
                    s=r['stages'][self.status_index]
                    s['finished_monotonic']=s['deadline_monotonic']+late
                    s['finished_epoch']=s['started_epoch']+s['finished_monotonic']-s['started_monotonic']
                self.rejected(change)

    def test_clock_source_and_cap_cross_evidence(self):
        mutations=[lambda r:r['stages'][self.status_index].update(source_sha='f'*40),
            lambda r:r['stages'][self.status_index].update(budget_phase='cleanup'),
            lambda r:r['stages'][self.status_index].update(timeout_seconds=421),
            lambda r:r['stages'][self.status_index].update(setup_command_cap_seconds=421),
            lambda r:r['stages'][self.status_index].update(finished_epoch=1),
            lambda r:r['stages'][self.status_index].update(started_monotonic=float('nan')),
            lambda r:r['budget'].update(run_id='foreign')]
        for change in mutations:
            with self.subTest(change=change):self.rejected(change)

    def test_creation_ids_are_bound_to_actual_output_bytes(self):
        for position in (4,5,6):
            self.rejected(lambda r:r['stages'][position].update(stdout_sha256='0'*64))

    def test_proof_is_reconstructed_not_trusted(self):
        for key,value in [('boot_stage_index',0),('bootstatus_stage_index',0),('source_sha','f'*40),
                          ('run_id','foreign'),('attempt','2'),('completed_monotonic',999),
                          ('bootstatus_file','other.log'),('udid','booted')]:
            with self.subTest(key=key):
                self.rejected(lambda r:r['setup_proof']['events'][0].update({key:value}))
        self.rejected(lambda r:r['setup_proof']['events'].reverse())
        self.rejected(lambda r:r['setup_proof'].update(connectivity='connected'))
        self.rejected(lambda r:r['setup_proof'].update(continued_readiness=True))

    def test_missing_corrupted_overflow_and_role_mixed_output(self):
        name=self.events[-1]['bootstatus_file']
        for value in (None,b'other',b'x'*(BOOT_OUTPUT_LIMIT+1)):
            blobs=dict(self.blobs)
            if value is None:blobs.pop(name)
            else:blobs[name]=value
            with self.subTest(value=None if value is None else len(value)),self.assertRaises(ValueError):self.check(blobs=blobs)
        manifest=copy.deepcopy(self.manifest);manifest[name]['case']='phone'
        with self.assertRaises(ValueError):self.check(manifest=manifest)

    def test_empty_but_exactly_retained_output_is_not_readiness_evidence(self):
        r=copy.deepcopy(self.report);blobs=dict(self.blobs);manifest=copy.deepcopy(self.manifest)
        name=self.events[-1]['bootstatus_file'];blobs[name]=b''
        sha=hashlib.sha256(b'').hexdigest();manifest[name].update(bytes=0,sha256=sha)
        r['stages'][self.status_index].update(stdout_bytes=0,stdout_sha256=sha)
        self.check(r,blobs,manifest)
        self.assertEqual(r['setup_proof']['continued_readiness'],'unobserved')

    def test_negative_or_invalid_utf8_output_cannot_be_reinterpreted(self):
        for raw in (b'device timed out',b'execution time allowance exceeded',b'test may have hung',b'\xff'):
            r=copy.deepcopy(self.report);blobs=dict(self.blobs);manifest=copy.deepcopy(self.manifest)
            name=self.events[-1]['bootstatus_file'];blobs[name]=raw;sha=hashlib.sha256(raw).hexdigest()
            manifest[name].update(bytes=len(raw),sha256=sha)
            r['stages'][self.status_index].update(stdout_bytes=len(raw),stdout_sha256=sha)
            with self.subTest(raw=raw),self.assertRaises(ValueError):self.check(r,blobs,manifest)

    def test_intervening_device_change_before_real_xctest_invalidates_events(self):
        def change(r):
            row=copy.deepcopy(r['stages'][self.status_index]);row['phase']='actual_cold'
            row['command']=['xcrun','simctl','shutdown',r['device']['udid']]
            r['stages'].insert(self.status_index+1,row)
        self.rejected(change)

    def test_later_exact_case_device_and_source_gates_remain_required(self):
        r=copy.deepcopy(self.report);r['stages'][r['cases'][0]['stage_index']]['command'][9]='platform=watchOS Simulator,id=booted'
        self.assertFalse(result.validate_result(r,self.root)['complete'])
        expected={**self.report['source'],'sha':'f'*40}
        self.assertFalse(result.validate_result(self.report,self.root,expected_source=expected)['complete'])
        r=copy.deepcopy(self.report);r['cases']=[]
        self.assertFalse(result.validate_result(r,self.root)['complete'])


if __name__ == '__main__':
    unittest.main()
