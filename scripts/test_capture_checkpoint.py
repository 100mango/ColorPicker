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
        checkpoint._containers.clear()
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

    def test_nonzero_permission_result_is_not_retried(self):
        result,count = self.run_capture(lambda command,**_: subprocess.CompletedProcess(command,13,stdout='',stderr='Synthetic access denied'))
        self.assertFalse(result['success']); self.assertEqual(count,1)
        self.assertEqual(result['exit'],13)
        self.assertFalse((self.output/'manifest.json').exists())

    def test_oversize_image_is_rejected_before_manifest_or_success(self):
        def behavior(command, **_):
            with Path(command[-1]).open('wb') as file: file.truncate(3_000_001)
            return subprocess.CompletedProcess(command,0,stdout='',stderr='')
        result,count = self.run_capture(behavior)
        self.assertFalse(result['success']); self.assertEqual(count,1)
        self.assertFalse((self.output/(self.identifier+'.jpeg')).exists())
        self.assertFalse((self.output/'manifest.json').exists())


if __name__=='__main__': unittest.main()
