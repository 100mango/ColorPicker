"""Portable closed-profile ownership adversaries; no Apple command is executed."""
import contextlib
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import uikit_managed_device as managed
from uikit_runtime_diagnostics import read_identity
from uikit_warmup import Warmup, WarmupFailed

NEW = 'AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE'
OLD = 'BBBBBBBB-1111-2222-3333-CCCCCCCCCCCC'
OTHER = 'CCCCCCCC-1111-2222-3333-DDDDDDDDDDDD'
TYPES = {'iPadMini': 'com.apple.CoreSimulator.SimDeviceType.iPad-mini-A17-Pro',
         'iPadLarge': 'com.apple.CoreSimulator.SimDeviceType.iPad-Pro-13-inch-M5',
         'iPhoneCompact': 'com.apple.CoreSimulator.SimDeviceType.iPhone-SE-3rd-generation',
         'iPhoneLarge': 'com.apple.CoreSimulator.SimDeviceType.iPhone-18-Pro-Max'}
ENV = {'GITHUB_REPOSITORY': managed.REPOSITORY, 'GITHUB_REF': managed.REF,
       'GITHUB_WORKFLOW_REF': managed.WORKFLOW, 'GITHUB_ACTIONS': 'true',
       'GITHUB_JOB': 'compatibility', 'RUNNER_OS': 'macOS', 'TC_TEST_FAMILY': 'iPadMini',
       'GITHUB_EVENT_NAME': 'push', 'GITHUB_SHA': 'a' * 40, 'GITHUB_WORKFLOW_SHA': 'a' * 40,
       'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '1'}


class ManagedFixture(unittest.TestCase):
    def setUp(self):
        previous = Path.cwd()
        folder = tempfile.TemporaryDirectory(prefix='UIKit managed ')
        os.chdir(folder.name)
        self.addCleanup(folder.cleanup)
        self.addCleanup(os.chdir, previous)
        environment = patch.dict(os.environ, ENV, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        quiet = contextlib.redirect_stdout(io.StringIO())
        quiet.__enter__()
        self.addCleanup(quiet.__exit__, None, None, None)
        self.tick = 100.0
        self.calls = []

    def initial(self, family='iPadMini'):
        return {'runtimes': [{'identifier': managed.RUNTIME, 'isAvailable': True}],
                'devicetypes': [{'name': managed.PROFILES[family], 'identifier': TYPES[family]}],
                'devices': {managed.RUNTIME: [{'udid': OLD, 'name': 'Existing image template'}]}}

    def after(self, family='iPadMini', state='Shutdown'):
        with patch.dict(os.environ, {'TC_TEST_FAMILY': family}):
            name = managed.owned_name(managed.require_job(family))
        return {'devices': {managed.RUNTIME: [{'udid': NEW, 'name': name,
                'deviceTypeIdentifier': TYPES[family], 'isAvailable': True, 'state': state}]}}

    def harness(self, family='iPadMini', initial=None, returned=None, after=None, action=None):
        os.environ['TC_TEST_FAMILY'] = family
        answers = [json.dumps(self.initial(family) if initial is None else initial),
                   NEW + '\n' if returned is None else returned,
                   json.dumps(self.after(family) if after is None else after)]
        self.calls = []
        def runner(command, *, timeout):
            index = len(self.calls)
            self.calls.append((command, timeout))
            self.assertTrue((Path('build') / (family + '-runtime-command-uncertain')).is_file())
            self.tick += 0.1
            if action is not None:
                action(index, command)
            return subprocess.CompletedProcess(command, 0, answers[index], '')
        return Warmup(family, started=100, clock=lambda: self.tick, runner=runner)

    def create(self, **kwargs):
        controller = self.harness(**kwargs)
        identity = managed.create_owned_device(controller)
        return controller, identity

    def paths(self, family='iPadMini'):
        return (Path('build') / (family + '-simulator.json'),
                Path('build') / (family + '-managed-device.json'))

    def reject_create(self, expected_calls, **kwargs):
        controller = self.harness(**kwargs)
        with self.assertRaises((ValueError, OSError, WarmupFailed)):
            managed.create_owned_device(controller)
        self.assertEqual(len(self.calls), expected_calls)
        self.assertFalse(self.paths(controller.family)[0].exists())
        return controller

    def rewrite_receipt(self, change):
        path = self.paths()[1]
        value = json.loads(path.read_text())
        change(value)
        path.write_text(json.dumps(value))

    def lookup(self, after=None, action=None):
        self.calls = []
        def runner(command, *, timeout):
            self.calls.append((command, timeout))
            if action is not None:
                action()
            return subprocess.CompletedProcess(command, 0,
                json.dumps(self.after(state='Booted') if after is None else after), '')
        controller = Warmup('iPadMini', started=100, clock=lambda: self.tick, runner=runner)
        return managed.read_managed_device('iPadMini', controller.command, controller.require_time)


class CanonicalIdentity(ManagedFixture):
    def test_exact_actual_workflow_guard_and_allowed_events(self):
        for event in ('push', 'workflow_dispatch'):
            with self.subTest(event=event), patch.dict(os.environ, {'GITHUB_EVENT_NAME': event}):
                result = managed.require_job('iPadMini')
                self.assertEqual(result['workflow_ref'],
                    '100mango/ColorPicker/.github/workflows/ios.yml@refs/heads/codex/platform-integration')
                self.assertEqual(result['job'], 'compatibility')
                self.assertEqual(result['event'], event)
        for key in ENV:
            with self.subTest(key=key), patch.dict(os.environ, {key: 'wrong'}):
                with self.assertRaises(ValueError):
                    managed.require_job('iPadMini')

    def test_compile_and_diagnostic_jobs_cannot_own_devices(self):
        for job in ('compile-prerequisites', 'mini-direct-xctest', 'compile', 'ios'):
            controller = self.harness()
            with self.subTest(job=job), patch.dict(os.environ, {'GITHUB_JOB': job}):
                with self.assertRaises(ValueError):
                    managed.create_owned_device(controller)
                self.assertEqual(self.calls, [])

    def test_unknown_family_and_noncanonical_ids_fail_without_commands(self):
        for family in ('Mini', 'LargePhone', 'unknown', '../iPadMini'):
            with self.subTest(family=family), self.assertRaises(ValueError):
                managed.require_job(family)
        for key, value in [('GITHUB_RUN_ID', '0'), ('GITHUB_RUN_ID', '01'),
                           ('GITHUB_RUN_ATTEMPT', '-1'), ('GITHUB_RUN_ID', '1' * 21),
                           ('GITHUB_SHA', 'A' * 40), ('GITHUB_SHA', 'a' * 39)]:
            with self.subTest(key=key, value=value), patch.dict(os.environ, {key: value}):
                with self.assertRaises(ValueError):
                    managed.require_job('iPadMini')

    def test_name_binds_full_source_run_attempt_and_family(self):
        context = managed.require_job('iPadMini')
        baseline = managed.owned_name(context)
        self.assertIn('a' * 40, baseline)
        for key, value in [('sha', 'b' * 40), ('run_id', '124'), ('run_attempt', '2'),
                           ('family', 'iPadLarge')]:
            self.assertNotEqual(managed.owned_name({**context, key: value}), baseline)


class FreshConfiguration(ManagedFixture):
    def test_all_four_fixed_profiles_only_create_and_readback(self):
        self.assertEqual(managed.PROFILES, {'iPadMini': 'iPad mini (A17 Pro)',
            'iPadLarge': 'iPad Pro 13-inch (M5)', 'iPhoneCompact': 'iPhone SE (3rd generation)',
            'iPhoneLarge': 'iPhone 18 Pro Max'})
        for family in managed.PROFILES:
            with self.subTest(family=family):
                controller, identity = self.create(family=family)
                binding = managed.read_binding(family)
                self.assertEqual(identity, read_identity(family))
                self.assertEqual(set(identity), {'family', 'udid', 'runtime', 'started'})
                self.assertEqual(binding['identity'], identity)
                receipt = binding['receipt']
                self.assertEqual(self.calls, [(managed.INVENTORY, 30),
                    (['xcrun', 'simctl', 'create', managed.owned_name(binding['context']),
                     TYPES[family], managed.RUNTIME], 60), (managed.READBACK, 30)])
                self.assertEqual(receipt['status'], 'configured_shutdown_device_only')
                self.assertEqual(receipt['readback_state'], 'Shutdown')
                self.assertEqual(receipt['initial_device_count'], 1)
                self.assertTrue(receipt['absent_from_initial_inventory'])
                self.assertEqual(receipt['deployment_owner'], 'xcodebuild')
                self.assertEqual(receipt['pretest_boot_completion'], 'not_requested')
                self.assertEqual(receipt['pretest_installed_bytes'], 'not_observed')
                self.assertNotIn('installed', identity)
                self.assertFalse(controller.pending.exists())

    def test_empty_initial_inventory_is_valid(self):
        value = self.initial()
        value['devices'] = {}
        self.create(initial=value)
        self.assertEqual(managed.read_binding('iPadMini')['receipt']['initial_device_count'], 0)

    def test_missing_or_unavailable_runtime_has_no_fallback(self):
        value = self.initial()
        value['runtimes'][0]['isAvailable'] = False
        self.reject_create(1, initial=value)

    def test_foreign_runtime_has_no_fallback(self):
        value = self.initial()
        value['runtimes'][0]['identifier'] = 'com.apple.CoreSimulator.SimRuntime.iOS-26-0'
        self.reject_create(1, initial=value)

    def test_duplicate_runtime_is_rejected(self):
        value = self.initial()
        value['runtimes'] *= 2
        self.reject_create(1, initial=value)

    def test_large_ipad_does_not_accept_another_13_inch_model(self):
        value = self.initial('iPadLarge')
        value['devicetypes'][0]['name'] = 'iPad Pro 13-inch (M4)'
        self.reject_create(1, family='iPadLarge', initial=value)

    def test_missing_compact_se3_does_not_choose_new_iphone(self):
        value = self.initial('iPhoneCompact')
        value['devicetypes'][0]['name'] = 'iPhone 18'
        self.reject_create(1, family='iPhoneCompact', initial=value)

    def test_duplicate_matching_type_name_rejected(self):
        value = self.initial()
        value['devicetypes'].append({**value['devicetypes'][0], 'identifier': TYPES['iPadLarge']})
        self.reject_create(1, initial=value)

    def test_foreign_name_aliasing_selected_type_identifier_rejected(self):
        value = self.initial()
        value['devicetypes'].append({'name': 'Foreign device', 'identifier': TYPES['iPadMini']})
        self.reject_create(1, initial=value)

    def test_invalid_type_identifier_rejected(self):
        value = self.initial()
        value['devicetypes'][0]['identifier'] = '../../foreign'
        self.reject_create(1, initial=value)

    def test_existing_owned_name_is_not_reused(self):
        value = self.initial()
        value['devices'][managed.RUNTIME][0]['name'] = managed.owned_name(managed.require_job('iPadMini'))
        self.reject_create(1, initial=value)

    def test_duplicate_uuid_across_runtimes_rejected(self):
        value = self.initial()
        value['devices']['foreign-runtime'] = copy.deepcopy(value['devices'][managed.RUNTIME])
        self.reject_create(1, initial=value)

    def test_lowercase_initial_uuid_alias_rejected(self):
        value = self.initial()
        value['devices'][managed.RUNTIME][0]['udid'] = OLD.lower()
        self.reject_create(1, initial=value)

    def test_invalid_foreign_inventory_rows_are_not_ignored(self):
        value = self.initial()
        value['devices']['foreign-runtime'] = [{'udid': 'not-a-uuid', 'name': 'Other'}]
        self.reject_create(1, initial=value)

    def test_existing_uuid_creation_response_stops_without_readback(self):
        self.reject_create(2, returned=OLD)
        self.assertEqual(json.loads(self.paths()[1].read_text())['status'], 'creation_pending')

    def test_lowercase_creation_response_stops_without_readback(self):
        self.reject_create(2, returned=NEW.lower())

    def test_two_uuid_creation_response_stops_without_readback(self):
        self.reject_create(2, returned=NEW + '\n' + OTHER)

    def test_creation_and_uuid_are_persisted_before_corresponding_dispatch(self):
        statuses = []
        def observe(index, command):
            if index:
                value = json.loads(self.paths()[1].read_text())
                statuses.append(value['status'])
                if index == 2:
                    self.assertEqual(value['returned_uuid'], NEW)
                    self.assertTrue(value['absent_from_initial_inventory'])
        self.create(action=observe)
        self.assertEqual(statuses, ['creation_pending', 'readback_pending'])

    def test_earlier_binding_cannot_be_overwritten(self):
        self.create()
        controller = self.harness()
        with self.assertRaises(ValueError):
            managed.create_owned_device(controller)
        self.assertEqual(self.calls, [])

    def test_creation_timeout_retains_latch_and_no_extra_command(self):
        def stop(index, command):
            if index == 1:
                error = subprocess.TimeoutExpired(command, 60)
                error.cleanup_confirmed = True
                raise error
        controller = self.reject_create(2, action=stop)
        self.assertTrue(controller.pending.exists())
        with self.assertRaises((ValueError, FileExistsError)):
            managed.create_owned_device(controller)
        self.assertEqual(len(self.calls), 2)

    def test_late_creation_zero_exit_retains_latch_and_no_readback(self):
        def late(index, command):
            if index == 1:
                self.tick += 60.1
        controller = self.reject_create(2, action=late)
        self.assertTrue(controller.pending.exists())

    def test_context_mutation_during_creation_stops_without_readback(self):
        def mutate(index, command):
            if index == 1:
                os.environ['GITHUB_RUN_ATTEMPT'] = '2'
        self.reject_create(2, action=mutate)

    def test_receipt_mutation_during_creation_stops_without_readback(self):
        def mutate(index, command):
            if index == 1:
                self.paths()[1].write_text('{}')
        self.reject_create(2, action=mutate)

    def test_receipt_mutation_during_readback_stops_before_identity_publication(self):
        def mutate(index, command):
            if index == 2:
                self.paths()[1].write_text('{}')
        self.reject_create(3, action=mutate)

    def test_stale_identity_inserted_during_inventory_stops_before_create(self):
        def mutate(index, command):
            if index == 0:
                self.paths()[0].write_text('{}')
        controller = self.harness(action=mutate)
        with self.assertRaises(ValueError):
            managed.create_owned_device(controller)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.paths()[0].read_text(), '{}')

    def test_identity_inserted_during_create_stops_before_readback(self):
        def mutate(index, command):
            if index == 1:
                self.paths()[0].write_text('{}')
        controller = self.harness(action=mutate)
        with self.assertRaises(ValueError):
            managed.create_owned_device(controller)
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.paths()[0].read_text(), '{}')

    def test_inventory_and_readback_timeout_never_dispatch_an_extra_command(self):
        for failure in (0, 2):
            with self.subTest(failure=failure):
                def stop(index, command):
                    if index == failure:
                        error = subprocess.TimeoutExpired(command, 30)
                        error.cleanup_confirmed = False
                        raise error
                controller = self.reject_create(failure + 1, action=stop)
                self.assertTrue(controller.pending.exists())
                controller.pending.unlink()
                self.paths()[1].unlink(missing_ok=True)


class ReadbackSafety(ManagedFixture):
    def test_each_owned_configuration_field_is_required(self):
        for key, value in [('udid', OTHER), ('name', 'Foreign'),
                           ('deviceTypeIdentifier', TYPES['iPadLarge']), ('isAvailable', False),
                           ('state', 'Booted')]:
            with self.subTest(key=key):
                after = self.after()
                after['devices'][managed.RUNTIME][0][key] = value
                self.reject_create(3, after=after)
                self.paths()[1].unlink()

    def test_created_device_under_foreign_runtime_rejected(self):
        after = self.after()
        after['devices']['com.apple.CoreSimulator.SimRuntime.iOS-26-0'] = after['devices'].pop(managed.RUNTIME)
        self.reject_create(3, after=after)

    def test_missing_created_device_is_not_reselected(self):
        self.reject_create(3, after={'devices': {managed.RUNTIME: []}})

    def test_foreign_uuid_with_owned_name_is_ambiguous(self):
        after = self.after()
        after['devices'][managed.RUNTIME].append({**after['devices'][managed.RUNTIME][0], 'udid': OTHER})
        self.reject_create(3, after=after)

    def test_owned_uuid_alias_with_foreign_name_is_ambiguous(self):
        after = self.after()
        after['devices']['foreign'] = [{**after['devices'][managed.RUNTIME][0], 'name': 'Foreign'}]
        self.reject_create(3, after=after)

    def test_lowercase_uuid_alias_in_foreign_readback_is_rejected(self):
        after = self.after()
        after['devices']['foreign'] = [{'udid': NEW.lower(), 'name': 'Foreign'}]
        self.reject_create(3, after=after)

    def test_duplicate_unrelated_uuid_is_still_rejected(self):
        after = self.after()
        after['devices']['foreign'] = [{'udid': OLD, 'name': 'One'}, {'udid': OLD, 'name': 'Two'}]
        self.reject_create(3, after=after)

    def test_inventory_shape_and_entry_bounds(self):
        for value in ({}, {'devices': []}, {'devices': {'a': {}}},
                      {'devices': {'a': [{'udid': OLD, 'name': 'x'}] * 513}},
                      {'devices': {str(i): [] for i in range(129)}}):
            with self.subTest(value=str(value)[:80]), self.assertRaises(ValueError):
                managed._device_rows(value)

    def test_strict_json_duplicate_key_nonfinite_and_byte_bounds(self):
        for raw in ('{"devices":{},"devices":{}}', '{"devices":{},"bad":NaN}',
                    '[]', '{} ' + ' ' * 1_000_000):
            with self.subTest(raw=raw[:80]), self.assertRaises(ValueError):
                managed._json_inventory(raw)


class BindingSafety(ManagedFixture):
    def test_host_only_binding_uses_no_simulator_command(self):
        self.create()
        with patch.object(Warmup, 'command', side_effect=AssertionError('No simulator command')):
            binding = managed.read_binding('iPadMini')
        self.assertEqual(binding['identity']['udid'], NEW)
        for key, path in [('identity_sha256', self.paths()[0]), ('receipt_sha256', self.paths()[1])]:
            self.assertEqual(binding[key], hashlib.sha256(path.read_bytes()).hexdigest())

    def test_later_inventory_reuses_owned_uuid_and_accepts_booted_state(self):
        self.create()
        before = managed.read_binding('iPadMini')
        self.assertEqual(self.lookup(), before)
        self.assertEqual(self.calls, [(managed.READBACK, 30)])
        self.assertEqual(managed.read_binding('iPadMini'), before)

    def test_later_inventory_does_not_require_booted_state(self):
        self.create()
        self.assertEqual(self.lookup(after=self.after())['identity']['udid'], NEW)

    def test_foreign_context_never_queries_current_inventory(self):
        self.create()
        for key, value in [('GITHUB_SHA', 'b' * 40), ('GITHUB_WORKFLOW_SHA', 'b' * 40),
                           ('GITHUB_RUN_ID', '124'), ('GITHUB_RUN_ATTEMPT', '2'),
                           ('GITHUB_WORKFLOW_REF', 'other'), ('TC_TEST_FAMILY', 'iPadLarge'),
                           ('GITHUB_EVENT_NAME', 'workflow_dispatch')]:
            with self.subTest(key=key), patch.dict(os.environ, {key: value}):
                with self.assertRaises(ValueError):
                    self.lookup()
                self.assertEqual(self.calls, [])

    def test_foreign_receipt_context_rejected_without_inventory(self):
        self.create()
        path = self.paths()[1]
        baseline = path.read_bytes()
        for key, value in [('sha', 'b' * 40), ('workflow_sha', 'b' * 40), ('run_id', '124'),
                           ('run_attempt', '2'), ('family', 'iPadLarge'), ('workflow_ref', 'foreign')]:
            with self.subTest(key=key):
                path.write_bytes(baseline)
                self.rewrite_receipt(lambda receipt: receipt['context'].update({key: value}))
                with self.assertRaises(ValueError):
                    self.lookup()
                self.assertEqual(self.calls, [])

    def test_incomplete_and_overstated_receipt_rejected_without_inventory(self):
        self.create()
        path = self.paths()[1]
        baseline = path.read_bytes()
        for key, value in [('schema', True), ('status', 'readback_pending'),
                           ('pretest_installed_bytes', 'verified'), ('pretest_boot_completion', 'completed'),
                           ('deployment_owner', 'simctl'), ('requested_name', 'Existing image template'),
                           ('initial_device_count', True), ('absent_from_initial_inventory', 1),
                           ('device_type', '../foreign'), ('identity_sha256', 'b' * 64)]:
            with self.subTest(key=key):
                path.write_bytes(baseline)
                self.rewrite_receipt(lambda receipt: receipt.update({key: value}))
                with self.assertRaises(ValueError):
                    self.lookup()
                self.assertEqual(self.calls, [])

    def test_receipt_unknown_and_duplicate_fields_rejected(self):
        self.create()
        path = self.paths()[1]
        baseline = path.read_text()
        for raw in (baseline.rstrip()[:-1] + ', "extra": true}',
                    baseline.rstrip()[:-1] + ', "schema": 1}'):
            path.write_text(raw)
            with self.assertRaises(ValueError):
                managed.read_binding('iPadMini')

    def test_identity_byte_rewrite_invalidates_receipt_without_inventory(self):
        self.create()
        path = self.paths()[0]
        path.write_text(json.dumps(json.loads(path.read_text())))
        with self.assertRaises(ValueError):
            self.lookup()
        self.assertEqual(self.calls, [])

    def test_identity_mutation_during_inventory_blocks_later_work(self):
        self.create()
        def mutate():
            path = self.paths()[0]
            value = json.loads(path.read_text())
            value['udid'] = OTHER
            path.write_text(json.dumps(value))
        with self.assertRaises(ValueError):
            self.lookup(action=mutate)
        self.assertEqual(self.calls, [(managed.READBACK, 30)])

    def test_receipt_byte_mutation_during_inventory_blocks_later_work(self):
        self.create()
        def mutate():
            path = self.paths()[1]
            path.write_text(json.dumps(json.loads(path.read_text())))
        with self.assertRaises(ValueError):
            self.lookup(action=mutate)
        self.assertEqual(self.calls, [(managed.READBACK, 30)])

    def test_current_device_mutation_does_not_trigger_reselection(self):
        self.create()
        after = self.after(state='Booted')
        after['devices'][managed.RUNTIME][0]['deviceTypeIdentifier'] = TYPES['iPadLarge']
        with self.assertRaises(ValueError):
            self.lookup(after=after)
        self.assertEqual(self.calls, [(managed.READBACK, 30)])

    def test_unknown_device_state_rejected(self):
        self.create()
        with self.assertRaises(ValueError):
            self.lookup(after=self.after(state='Booting'))
        self.assertEqual(self.calls, [(managed.READBACK, 30)])

    def test_prior_uncertainty_blocks_inventory(self):
        self.create()
        Path('build/iPadMini-runtime-command-uncertain').write_text('unknown earlier exit')
        with self.assertRaises(WarmupFailed):
            self.lookup()
        self.assertEqual(self.calls, [])

    def test_receipt_symlink_hardlink_and_fifo_rejected_without_commands(self):
        self.create()
        path = self.paths()[1]
        data = path.read_bytes()
        other = Path('outside')
        other.write_bytes(data)
        for alias in ('symlink', 'hardlink', 'fifo'):
            with self.subTest(alias=alias):
                path.unlink()
                if alias == 'symlink':
                    path.symlink_to(other.resolve())
                elif alias == 'hardlink':
                    os.link(other, path)
                else:
                    os.mkfifo(path)
                with self.assertRaises((ValueError, OSError)):
                    self.lookup()
                self.assertEqual(self.calls, [])

    def test_identity_hardlink_and_linked_build_root_rejected(self):
        self.create()
        path = self.paths()[0]
        os.link(path, 'alias')
        with self.assertRaises(ValueError):
            managed.read_binding('iPadMini')
        Path('alias').unlink()
        Path('build').rename('actual-build')
        Path('build').symlink_to('actual-build', target_is_directory=True)
        with self.assertRaises(OSError):
            managed.read_binding('iPadMini')

    def test_oversized_receipt_rejected_before_inventory(self):
        self.create()
        self.paths()[1].write_bytes(b' ' * (managed.RECEIPT_LIMIT + 1))
        with self.assertRaises(ValueError):
            self.lookup()
        self.assertEqual(self.calls, [])

    def test_identity_schema_is_not_extended_or_lenient(self):
        self.create()
        path = self.paths()[0]
        baseline = path.read_text()
        for raw in (baseline.rstrip()[:-1] + ', "source": "extra"}',
                    baseline.rstrip()[:-1] + ', "family": "iPadMini"}'):
            with self.subTest(raw=raw[-70:]):
                path.write_text(raw)
                with self.assertRaises(ValueError):
                    self.lookup()
                self.assertEqual(self.calls, [])

    def test_receipt_changes_during_trusted_fd_read_are_rejected(self):
        self.create()
        path = self.paths()[1]
        original = os.read
        changed = [False]
        def mutate(descriptor, count):
            data = original(descriptor, count)
            if not changed[0]:
                changed[0] = True
                with path.open('ab') as output:
                    output.write(b' ')
            return data
        with patch.object(managed.os, 'read', side_effect=mutate):
            with self.assertRaises(ValueError):
                managed._read_file(path, managed.RECEIPT_LIMIT)


class FixedRepairRouteTests(unittest.TestCase):
    def test_only_two_exact_ref_workflow_pairs_are_admitted(self):
        for ref,workflow in ((managed.REF,managed.WORKFLOW),(managed.REPAIR_REF,managed.REPAIR_WORKFLOW)):
            with patch.dict(os.environ,{**ENV,'GITHUB_REF':ref,'GITHUB_WORKFLOW_REF':workflow},clear=True):
                result=managed.require_job('iPadMini')
                self.assertEqual(result['ref'],ref);self.assertEqual(result['workflow_ref'],workflow)
        for ref,workflow in ((managed.REF,managed.REPAIR_WORKFLOW),(managed.REPAIR_REF,managed.WORKFLOW),
                             ('refs/heads/foreign',managed.REPAIR_WORKFLOW)):
            with patch.dict(os.environ,{**ENV,'GITHUB_REF':ref,'GITHUB_WORKFLOW_REF':workflow},clear=True):
                with self.assertRaises(ValueError):managed.require_job('iPadMini')

    def test_repair_route_cannot_change_source_repo_job_or_family(self):
        repair={**ENV,'GITHUB_REF':managed.REPAIR_REF,'GITHUB_WORKFLOW_REF':managed.REPAIR_WORKFLOW}
        for key,bad in [('GITHUB_REPOSITORY','foreign/ColorPicker'),('GITHUB_JOB','native-platform'),
                        ('GITHUB_WORKFLOW_SHA','b'*40),('TC_TEST_FAMILY','other'),('GITHUB_EVENT_NAME','pull_request')]:
            with patch.dict(os.environ,{**repair,key:bad},clear=True):
                with self.assertRaises(ValueError):managed.require_job('iPadMini')

    def test_existing_workflow_adds_only_fixed_push_branch_and_two_guards(self):
        root=Path(__file__).resolve().parents[1]
        source=(root/'.github/workflows/ios.yml').read_text()
        self.assertIn('branches: [codex/platform-integration, codex/uikit-hosted-repair]',source)
        guard='[[ "$GITHUB_REF" == refs/heads/codex/platform-integration || "$GITHUB_REF" == refs/heads/codex/uikit-hosted-repair ]]'
        self.assertEqual(source.count(guard),2)
        native=(root/'.github/workflows/apple-platforms.yml').read_text()
        self.assertNotIn('uikit-hosted-repair',native)
        self.assertIn('branches: [codex/platform-integration]',native)
        self.assertIn('family: [iPadMini, iPadLarge, iPhoneCompact, iPhoneLarge]',source)
        self.assertIn('max-parallel: 1',source)


if __name__ == '__main__':
    unittest.main()
