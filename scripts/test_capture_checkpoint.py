#!/usr/bin/env python3
"""Synthetic orchestration checks; these do not claim real simulator capture success."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import uuid
import capture_simulator_checkpoint as checkpoint


class CaptureCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root/'tmp').mkdir()
        self.identifier = str(uuid.uuid4()).upper()
        request = self.root/'tmp'/('TouchColor-capture-'+self.identifier+'.json')
        request.write_text(json.dumps({'id':self.identifier,'name':'Native Vision synthetic protocol test'}))
        self.ack = request.with_suffix('.ack')
        self.output = self.root/'images'
        checkpoint._containers.clear(); checkpoint._bindings.clear()
        self.lookup = patch.object(checkpoint,'check_output',return_value=str(self.root)+'\n')
        self.lookup.start(); self.addCleanup(self.lookup.stop)

    def run_capture(self, behavior):
        with patch.object(checkpoint,'run_captured',side_effect=behavior) as command:
            result = checkpoint.capture('synthetic-device','synthetic-runner',self.identifier,self.output)
        self.assertEqual(json.loads(self.ack.read_text()), result)
        return result, command.call_count

    def test_timeout_retries_same_held_request_once_with_distinct_output(self):
        files = []
        def behavior(command, **options):
            destination = Path(command[-1]); files.append(destination)
            destination.write_bytes(b'synthetic screenshot bytes')
            if len(files)==1:
                error=subprocess.TimeoutExpired(command,options['timeout']);error.cleanup_confirmed=True;raise error
            return subprocess.CompletedProcess(command,0,stdout='written',stderr='')
        result, count = self.run_capture(behavior)
        self.assertTrue(result['success']); self.assertEqual(count,2)
        self.assertNotEqual(files[0],files[1])
        self.assertEqual([a['exit'] for a in result['attempts']],[124,0])
        manifest = json.loads((self.output/'manifest.json').read_text())
        self.assertEqual(manifest[0]['attachments'][0]['exportedFileName'],files[1].name)

    def test_two_timeouts_acknowledge_failure_instead_of_succeeding_from_partial_file(self):
        def behavior(command, **options):
            Path(command[-1]).write_bytes(b'partial synthetic image')
            error=subprocess.TimeoutExpired(command,options['timeout']);error.cleanup_confirmed=True;raise error
        result,count = self.run_capture(behavior)
        self.assertFalse(result['success']); self.assertEqual(count,2)
        self.assertEqual([a['exit'] for a in result['attempts']],[124,124])
        self.assertFalse((self.output/'manifest.json').exists())

    def test_unconfirmed_cleanup_does_not_launch_a_second_capture(self):
        def behavior(command, **options):
            error=subprocess.TimeoutExpired(command,options['timeout']);error.cleanup_confirmed=False;raise error
        result,count = self.run_capture(behavior)
        self.assertFalse(result['success']); self.assertEqual(count,1)
        self.assertTrue(result['cleanup_unconfirmed'])

    def test_unconfirmed_host_prevents_lookup_and_capture(self):
        checkpoint._containers[('synthetic-device','synthetic-runner')]=self.root
        with patch.object(checkpoint,'check_output') as lookup, patch.object(checkpoint,'run_captured') as command:
            result=checkpoint.capture('synthetic-device','synthetic-runner',self.identifier,self.output,may_start=lambda: False)
        lookup.assert_not_called();command.assert_not_called()
        self.assertFalse(result['success']);self.assertTrue(result['acknowledged'])

    def test_host_cleanup_loss_prevents_capture_retry(self):
        permitted=True
        def behavior(command, **options):
            nonlocal permitted
            permitted=False
            error=subprocess.TimeoutExpired(command,options['timeout']);error.cleanup_confirmed=True;raise error
        with patch.object(checkpoint,'run_captured',side_effect=behavior) as command:
            result=checkpoint.capture('synthetic-device','synthetic-runner',self.identifier,self.output,may_start=lambda: permitted)
        self.assertEqual(command.call_count,1)
        self.assertTrue(result['cleanup_unconfirmed']);self.assertFalse(result['success'])
        self.assertEqual(json.loads(self.ack.read_text()),result)

    def test_nonzero_permission_result_is_not_retried(self):
        result,count = self.run_capture(lambda command,**_: subprocess.CompletedProcess(command,13,stdout='',stderr='Synthetic access denied'))
        self.assertFalse(result['success']); self.assertEqual(count,1)
        self.assertEqual(result['exit'],13)
        self.assertFalse((self.output/'manifest.json').exists())

    def test_nonzero_with_existing_pixels_cannot_pass_under_optimized_python(self):
        def behavior(command, **_):
            Path(command[-1]).write_bytes(b'synthetic partial screenshot')
            return subprocess.CompletedProcess(command,13,stdout='',stderr='Synthetic denied completion')
        result,count=self.run_capture(behavior)
        self.assertFalse(result['success']);self.assertEqual(count,1)
        self.assertFalse((self.output/'manifest.json').exists())

    def test_oversize_image_is_rejected_before_manifest_or_success(self):
        def behavior(command, **_):
            with Path(command[-1]).open('wb') as file: file.truncate(3_000_001)
            return subprocess.CompletedProcess(command,0,stdout='',stderr='')
        result,count = self.run_capture(behavior)
        self.assertFalse(result['success']); self.assertEqual(count,1)
        self.assertFalse((self.output/(self.identifier+'.jpeg')).exists())
        self.assertFalse((self.output/'manifest.json').exists())

    def test_ack_is_absent_during_partial_write_then_complete_at_publication(self):
        outcome = {'id': self.identifier, 'success': True, 'name': 'Native Vision synthetic atomic capture'}
        snapshots = []
        replace = checkpoint.os.replace
        def partial_dump(value, stream):
            encoded = json.dumps(value)
            stream.write(encoded[:1]); stream.flush()
            snapshots.append(self.ack.exists())
            stream.write(encoded[1:])
        def observe_publication(source, destination):
            self.assertEqual(Path(source).parent, self.ack.parent)
            self.assertFalse(self.ack.exists())
            self.assertEqual(json.loads(Path(source).read_text()), outcome)
            replace(source, destination)
            self.assertEqual(json.loads(self.ack.read_text()), outcome)
        with patch.object(checkpoint.json, 'dump', side_effect=partial_dump), \
             patch.object(checkpoint.os, 'replace', side_effect=observe_publication):
            checkpoint.publish_acknowledgement(self.ack, outcome)
        self.assertEqual(snapshots, [False])
        self.assertEqual(list(self.root.joinpath('tmp').glob('*.tmp')), [])

    def test_failed_ack_write_preserves_previous_complete_value_and_cleans_partial(self):
        original = {'success': False, 'error': 'synthetic previous result'}
        self.ack.write_text(json.dumps(original))
        with self.assertRaises(TypeError):
            checkpoint.publish_acknowledgement(self.ack, {'invalid': object()})
        self.assertEqual(json.loads(self.ack.read_text()), original)
        self.assertEqual(list(self.root.joinpath('tmp').glob('*.tmp')), [])

    def test_unhealthy_host_acknowledges_failure_using_only_known_container(self):
        checkpoint._containers[('synthetic-device', 'synthetic-runner')] = self.root
        with patch.object(checkpoint, 'check_output') as lookup, patch.object(checkpoint, 'run_captured') as launch:
            result = checkpoint.fail_cached_capture('synthetic-device', 'synthetic-runner', self.identifier, 'Diagnostic process exit unconfirmed')
        self.assertFalse(result['success']); self.assertTrue(result['acknowledged'])
        self.assertEqual(json.loads(self.ack.read_text()), result)
        lookup.assert_not_called(); launch.assert_not_called()

    def test_unhealthy_host_does_not_guess_a_replaced_runner_container(self):
        with patch.object(checkpoint, 'check_output') as lookup, patch.object(checkpoint, 'run_captured') as launch:
            result = checkpoint.fail_cached_capture('synthetic-device', 'synthetic-runner', self.identifier, 'Unconfirmed cleanup')
        self.assertFalse(result['success']); self.assertFalse(result['acknowledged'])
        self.assertFalse(self.ack.exists()); lookup.assert_not_called(); launch.assert_not_called()


class PrimedRunnerCaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'Devices';self.device=str(uuid.uuid4()).upper()
        self.runner='com.mango.touchColor.TouchColorVisionUITests.xctrunner'
        self.container=self.root/self.device/'data/Containers/Data/Application'/str(uuid.uuid4()).upper()
        (self.container/'tmp').mkdir(parents=True)
        self.lease=str(uuid.uuid4()).upper();self.request=str(uuid.uuid4()).upper()
        self.lease_file=self.container/'tmp'/('TouchColor-runner-'+self.lease+'.json')
        self.lease_file.write_text(json.dumps({'id':self.lease,'runner':self.runner}))
        self.capture_file=self.container/'tmp'/('TouchColor-capture-'+self.request+'.json')
        self.capture_file.write_text(json.dumps({'id':self.request,'name':'Native Vision Photos grid before selection diagnostic','runner':self.runner,'lease':self.lease}))
        checkpoint._containers.clear();checkpoint._bindings.clear()

    def prime(self):
        with patch.object(checkpoint,'check_output',return_value=str(self.container)) as lookup:
            value=checkpoint.prime_container(self.device,self.runner,self.lease,device_root=self.root)
        lookup.assert_called_once_with(['xcrun','simctl','get_app_container',self.device,self.runner,'data'],text=True,timeout=15)
        return value

    def test_current_runner_nonce_binds_supported_container_lookup_and_capture(self):
        binding=self.prime()
        self.assertTrue(binding['success'])
        self.assertEqual(json.loads(self.lease_file.with_suffix('.ack').read_text()),binding)
        def screenshot(command,**kwargs):
            Path(command[-1]).write_bytes(b'synthetic image')
            return subprocess.CompletedProcess(command,0,'written','')
        with patch.object(checkpoint,'check_output') as lookup,patch.object(checkpoint,'run_captured',side_effect=screenshot) as capture:
            result=checkpoint.capture(self.device,self.runner,self.request,self.container/'images',require_primed=True)
        lookup.assert_not_called();capture.assert_called_once();self.assertTrue(result['success'])
        self.assertEqual(json.loads(self.capture_file.with_suffix('.ack').read_text()),result)

    def test_wrong_device_or_runner_nonce_cannot_bind_cache(self):
        with patch.object(checkpoint,'check_output',return_value=str(self.container)):
            with self.assertRaises((ValueError,FileNotFoundError)):
                checkpoint.prime_container(str(uuid.uuid4()).upper(),self.runner,self.lease,device_root=self.root)
        self.lease_file.write_text(json.dumps({'id':self.lease,'runner':'another.runner'}))
        with self.assertRaises(ValueError):self.prime()
        self.assertEqual(checkpoint._bindings,{})

    def test_changed_or_missing_lease_never_relooks_up_or_writes_stale_ack(self):
        self.prime();self.lease_file.unlink()
        with patch.object(checkpoint,'check_output') as lookup,patch.object(checkpoint,'run_captured') as command:
            with self.assertRaises(ValueError):checkpoint.capture(self.device,self.runner,self.request,self.container/'images',require_primed=True)
            value=checkpoint.fail_cached_capture(self.device,self.runner,self.request,'stale',require_primed=True)
        lookup.assert_not_called();command.assert_not_called();self.assertFalse(value['acknowledged'])
        self.assertFalse(self.capture_file.with_suffix('.ack').exists())

    def test_replaced_container_identity_is_rejected_even_with_copied_nonce(self):
        self.prime();old=self.container.with_name(self.container.name+'-old');self.container.rename(old)
        (self.container/'tmp').mkdir(parents=True)
        self.lease_file.write_text(json.dumps({'id':self.lease,'runner':self.runner}))
        with self.assertRaisesRegex(ValueError,'identity changed'):checkpoint._primed_container(self.device,self.runner)

    def test_capture_lease_mismatch_or_symlink_is_rejected_without_ack_or_command(self):
        self.prime()
        wrong={'id':self.request,'name':'Native Vision synthetic','runner':self.runner,'lease':str(uuid.uuid4()).upper()}
        self.capture_file.write_text(json.dumps(wrong))
        with patch.object(checkpoint,'run_captured') as command:
            value=checkpoint.capture(self.device,self.runner,self.request,self.container/'images',require_primed=True)
            self.assertFalse(value['success']);self.assertFalse(self.capture_file.with_suffix('.ack').exists())
            self.capture_file.unlink();self.capture_file.symlink_to(self.lease_file)
            value=checkpoint.capture(self.device,self.runner,self.request,self.container/'images',require_primed=True)
            self.assertFalse(value['success']);self.assertFalse(self.capture_file.with_suffix('.ack').exists())
        command.assert_not_called()


if __name__=='__main__': unittest.main()
