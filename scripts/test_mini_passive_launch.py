"""Synthetic fixed two-process ownership tests; no simulator commands are run."""
import copy
import hashlib
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch

import mini_passive_launch as joint
import mini_passive_compatibility as compatibility
import test_mini_passive_compatibility as base
import mini_passive_status as console
import yaml

REAL_POPEN = subprocess.Popen


class Engine(base.Engine):
    def __init__(self, clock):
        super().__init__(clock)
        self.launch_duration=.1
        self.launch_text=b'com.mango.touchColor: 999\n'
        self.launch_stderr=b''
        self.launch_exit=0
    def popen(self, argv, **kwargs):
        self.calls.append((list(argv),kwargs.copy(),self.clock()))
        name='launcher' if argv[2]=='launch' else 'collector'
        duration=self.launch_duration if name=='launcher' else self.collector_duration
        output=self.launch_text if name=='launcher' else self.collector_text
        stderr=self.launch_stderr if name=='launcher' else self.stderr
        process=base.Process(self,name,output,stderr,duration)
        original=process.poll
        def poll():
            answer=original()
            if answer==0 and name=='launcher':process.returncode=self.launch_exit
            return process.returncode
        process.poll=poll
        self.processes.append(process)
        self.clock.advance(self.spawn_delay.get(name,0))
        if self.on_spawn:self.on_spawn(name,process)
        return process


class Harness(base.Harness):
    def setUp(self):
        super().setUp()
        self.engine=Engine(self.clock)
        self.budget.record={**self.budget.record,'lane':'mini-passive-launch','minutes':20}
        self.extra_env=patch.dict(os.environ,{'GITHUB_REF':joint.REF,'GITHUB_WORKFLOW_REF':joint.WORKFLOW,
                                             'GITHUB_JOB':'mini-passive-launch'})
        self.extra_env.start();self.addCleanup(self.extra_env.stop)
        (joint.APP_PLIST.parent/joint.EXECUTABLE).write_bytes(b'synthetic app code')
        self.warmup.mini_joint_identity = copy.deepcopy(self.identity)
        self.warmup.mini_joint_product = joint.product_identity()
        # Original harness patches shared module objects, but its bound side
        # effects need retargeting to this two-process engine.
        self.extra_patches=[patch.object(joint.subprocess,'Popen',side_effect=self.engine.popen),
            patch.object(joint.selectors,'DefaultSelector',side_effect=lambda:base.Selector(self.engine)),
            patch.object(joint.os,'read',side_effect=self.read),patch.object(joint.os,'killpg',side_effect=self.engine.kill),
            patch.object(joint,'group_exists',side_effect=self.engine.group),
            patch.object(joint,'_write_nonblocking',return_value=False)]
        for item in self.extra_patches:item.start();self.addCleanup(item.stop)
    def operation(self):return joint.JointCapture(self.warmup,preparation_started=100)
    def receipt(self):return json.loads(Path('build/iPadMini-passive-launch/receipt.json').read_bytes())


class JointTests(Harness):
    def test_silent_reader_allows_original_launch_and_never_qualifies(self):
        self.engine.collector_text=b''
        receipt=self.run_capture()
        self.assertEqual([x[0] for x in self.engine.calls],[
            ['xcrun','simctl','spawn',base.UUID,'log','stream','--info','--debug','--predicate','process == "TouchColor"'],
            ['xcrun','simctl','launch','--terminate-running-process',base.UUID,joint.APP]])
        self.assertEqual(receipt['readiness'],'unknown')
        self.assertFalse(receipt['warmup_admitted']);self.assertFalse(receipt['tests_executed'])
        self.assertEqual(receipt['reason'],'launch-observed');self.assertTrue(receipt['host_cleanup_confirmed'])
        self.assertEqual(receipt['joint_deadline'],185)
        self.assertEqual(self.budget.calls,[(65,65,20),(60,60,20)])
        self.no_later_command()

    def test_informational_stderr_is_unclassified_evidence(self):
        self.engine.stderr=b'Filtering log data using the selected process predicate\n'
        receipt=self.run_capture()
        self.assertEqual(receipt['reason'],'launch-observed')
        self.assertEqual(receipt['outputs']['collector_stderr']['raw_bytes'],len(self.engine.stderr))
        self.assertNotIn('reader_permission_indicator',receipt)

    def test_reader_permission_prevents_launch(self):
        self.engine.stderr=b'log: Operation not permitted\n'
        receipt=self.failed('reader-permission')
        self.assertEqual(len(self.engine.calls),1)
        self.assertFalse(receipt['app_launch_attempted']);self.no_later_command()

    def test_reader_zero_exit_before_launch_is_failure(self):
        self.engine.collector_duration=.001
        self.failed('reader-exited');self.assertEqual(len(self.engine.calls),1)

    def test_reader_exit_after_launch_aborts_both(self):
        self.engine.collector_duration=.07;self.engine.launch_duration=30
        receipt=self.failed('reader-exited')
        self.assertEqual(len(self.engine.calls),2)
        self.assertIsNone(receipt['processes']['launcher']['observed_work_exit'])
        self.assertTrue(receipt['host_cleanup_confirmed']);self.no_later_command()

    def test_original_sixty_second_launch_cap_is_absolute(self):
        self.engine.launch_duration=1000
        receipt=self.failed()
        self.assertLessEqual(self.clock(),185)
        self.assertAlmostEqual(receipt['launch_deadline']-self.engine.calls[1][2],60,places=9)
        self.assertIsNone(receipt['processes']['launcher']['observed_work_exit'])
        self.no_later_command()

    def test_late_reader_spawn_never_admits_launch(self):
        self.engine.spawn_delay['collector']=5.001
        self.failed('absolute-deadline');self.assertEqual(len(self.engine.calls),1)
        self.no_later_command()

    def test_late_launcher_spawn_keeps_same_envelope_and_cleanup(self):
        self.engine.spawn_delay['launcher']=60.1
        receipt=self.failed('absolute-deadline')
        self.assertLessEqual(self.clock(),185)
        self.assertTrue(receipt['host_cleanup_confirmed']);self.no_later_command()

    def test_insufficient_original_remainder_starts_nothing(self):
        self.clock.value=615.001
        self.failed('85-second');self.assertEqual(self.engine.calls,[])

    def test_source_device_or_code_change_prevents_launcher(self):
        def change(name,process):
            if name=='collector':(joint.APP_PLIST.parent/joint.EXECUTABLE).write_bytes(b'changed')
        self.engine.on_spawn=change
        self.failed('binding changed');self.assertEqual(len(self.engine.calls),1)

    def test_launcher_permission_or_nonzero_never_qualifies(self):
        self.engine.launch_stderr=b'launch: Permission denied\n'
        receipt=self.failed('launch-permission');self.assertFalse(receipt['warmup_admitted'])

    def test_two_descendants_share_one_twenty_second_cleanup(self):
        self.engine.descendants={'collector','launcher'};self.engine.unkillable={'collector','launcher'}
        operation=self.operation()
        with self.assertRaisesRegex(joint.CaptureFailed,'cleanup'):operation.run()
        receipt=operation.receipt  # Final persistence is deliberately omitted after tail expiry.
        started=receipt['events']['cleanup_started']['monotonic']
        self.assertLessEqual(self.clock()-started,20.00001)
        self.assertFalse(receipt['host_cleanup_confirmed']);self.no_later_command()

    def test_split_permission_indicator_and_other_stderr(self):
        buffer=joint.ReaderStderr(16)
        buffer.feed(b'informational text');self.assertIsNone(buffer.denial)
        buffer.feed(b' Permission de');buffer.feed(b'nied')
        self.assertEqual(buffer.denial,'EACCES');self.assertLessEqual(len(buffer.data()),16)

    def test_late_read_bytes_never_enter_the_observation(self):
        original=self.engine.read;late=[False]
        def read(fd,cap):
            value=original(fd,cap)
            if value and not late[0]:
                late[0]=True;self.clock.advance(5.25)
            return value
        self.engine.read=read
        receipt=self.failed('after its absolute deadline')
        self.assertEqual(len(self.engine.calls),1)
        self.assertEqual(receipt['outputs']['stream']['raw_bytes'],0)
        self.assertGreater(receipt['late_reads']['stream']['omitted_bytes'],0)
        self.no_later_command()

    def test_spawn_failure_is_unknown_cleanup_not_vacuous_success(self):
        operation=self.operation()
        with patch.object(joint.subprocess,'Popen',side_effect=PermissionError('synthetic denied')):
            with self.assertRaises(PermissionError):operation.run()
        self.assertFalse(operation.receipt['host_cleanup_confirmed'])
        self.assertEqual(operation.receipt['processes']['collector']['state'],'attempted')
        self.assertFalse(operation.receipt['app_launch_attempted'])
        self.no_later_command()

    def test_cancellation_after_each_spawn_stops_without_later_device_work(self):
        operation=self.operation()
        self.engine.on_spawn=lambda name,p:setattr(operation,'cancelled',signal.SIGTERM)
        with self.assertRaisesRegex(joint.CaptureFailed,'cancelled'):operation.run()
        self.assertEqual(len(self.engine.calls),1)
        self.assertEqual(operation.receipt['cancelled_signal'],signal.SIGTERM)
        self.no_later_command()

    def test_flood_and_binary_bytes_stay_inside_fixed_caps(self):
        self.engine.collector_text=b'\xff'+b'x'*200000
        self.engine.stderr=b'informational\n'*1000
        self.engine.launch_text=b'y'*20000;self.engine.launch_duration=2
        receipt=self.run_capture()
        for name,limit in (('stream',65536),('collector_stderr',4096),('launcher',8192)):
            row=receipt['outputs'][name]
            self.assertLessEqual(row['retained_bytes'],limit)
            raw=(Path('build/iPadMini-passive-launch')/(name+'.bin')).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(),row['sha256_retained'])
        self.assertTrue(receipt['outputs']['stream']['truncated'])
        self.assertLessEqual(Path('build/iPadMini-passive-launch/receipt.json').stat().st_size,8192)
        self.assertEqual(receipt['readiness'],'unknown')

    def test_capture_cannot_adopt_a_replaced_preparation_device_or_product(self):
        self.warmup.mini_joint_identity={**self.identity,'udid':'BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB'}
        with self.assertRaisesRegex(joint.CaptureFailed,'original selected'):self.run_capture()
        self.assertEqual(self.engine.calls,[])
        self.warmup.mini_joint_identity=copy.deepcopy(self.identity)
        self.warmup.mini_joint_product={'identifier':'other'}
        with self.assertRaisesRegex(joint.CaptureFailed,'original installed'):self.run_capture()
        self.assertEqual(self.engine.calls,[])

    def test_nonzero_launch_is_command_failure_even_with_reader_alive(self):
        self.engine.launch_exit=1
        receipt=self.failed('launch-nonzero')
        self.assertEqual(receipt['processes']['launcher']['observed_work_exit'],1)
        self.assertFalse(receipt['warmup_admitted']);self.no_later_command()

    def test_original_budget_lane_and_source_are_required(self):
        self.budget.record['lane']='iPadMini'
        with self.assertRaisesRegex(joint.CaptureFailed,'budget identity'):self.run_capture()
        self.assertEqual(self.engine.calls,[])

    def test_exact_disposable_workflow_is_required(self):
        with patch.dict(os.environ,{'GITHUB_WORKFLOW_REF':'other'}):
            with self.assertRaisesRegex(joint.CaptureFailed,'identity'):self.run_capture()
        self.assertEqual(self.engine.calls,[])

    def test_second_or_unplanned_spawn_cannot_be_admitted(self):
        operation=self.operation();operation._binding()
        with self.assertRaisesRegex(joint.CaptureFailed,'Unplanned'):
            operation._spawn('other',['xcrun','simctl','list'],200)
        with self.assertRaisesRegex(joint.CaptureFailed,'Unplanned'):
            operation._spawn('collector',['xcrun','simctl','shutdown',base.UUID],200)
        self.assertEqual(self.engine.calls,[])

    def test_summary_generated_record_fits_actual_darwin_limit(self):
        receipt=self.run_capture();receipt=copy.deepcopy(receipt)
        receipt.update(run_id='9'*20,run_attempt='9'*20,reason='failed-or-incomplete',status='failed_or_incomplete')
        for row in receipt['processes'].values():row.update(observed_work_exit=-255,exit=-255,host_cleanup_confirmed=False)
        sent=[]
        with patch.dict(os.environ,{'GITHUB_RUN_ID':'9'*20,'GITHUB_RUN_ATTEMPT':'9'*20}), \
             patch.object(joint,'_write_nonblocking',side_effect=lambda b:sent.append(b) or True):
            self.assertTrue(joint.emit_joint_summary(receipt))
        self.assertEqual(len(sent),1);self.assertLessEqual(len(sent[0]),512)
        value=json.loads(sent[0].split(b' ',1)[1]);self.assertEqual(value['source'],'memory')
        self.assertEqual(value['durability'],'unconfirmed');self.assertFalse(value['acceptance'])
        self.assertIsNone(value['readiness'])

    def test_summary_failure_does_not_change_observed_command_outcome(self):
        with patch.object(joint,'_write_nonblocking',side_effect=OSError('unavailable output')):
            receipt=self.run_capture()
        self.assertEqual(receipt['reason'],'launch-observed');self.no_later_command()

    def test_final_file_failure_cannot_enable_later_actions(self):
        operation=self.operation();original=Path.open
        def open_file(path,*args,**kwargs):
            if str(path).endswith('stream.bin'):raise OSError('synthetic output failure')
            return original(path,*args,**kwargs)
        with patch.object(Path,'open',new=open_file):
            with self.assertRaises(OSError):operation.run()
        self.assertTrue(operation.receipt['host_cleanup_confirmed'])
        self.assertFalse(operation.receipt['warmup_admitted']);self.no_later_command()

    def test_prepare_uses_original_build_install_and_boot_commands_only(self):
        calls=[];budget=self.budget
        class Setup:
            def __init__(self):self.budget=budget
            def command(self,command,seconds,**kwargs):
                calls.append((command,seconds,kwargs))
                if command==['git','rev-parse','HEAD']:return 'a'*40
                if command==['xcodebuild','-version']:return 'Xcode 27.0\nBuild version 27A266a\n'
                return ''
            def select(self):return base.UUID
        joint.prepare_joint(Setup())
        self.assertEqual(calls[-3:],[
            (['xcrun','simctl','boot',base.UUID],180,{'optional':True}),
            (['xcrun','simctl','bootstatus',base.UUID,'-b'],240,{}),
            (['xcrun','simctl','install',base.UUID,str(joint.APP_PLIST.parent)],300,{})])
        self.assertEqual(calls[3],(joint.BUILD,300,{'simulator':False}))
        self.assertFalse(any('launch' in command or 'terminate' in command or 'shutdown' in command
                             for command,_,_ in calls))

    def test_product_code_is_bounded_and_revalidated(self):
        before=joint.product_identity()
        (joint.APP_PLIST.parent/joint.EXECUTABLE).write_bytes(b'changed code')
        self.assertNotEqual(joint.product_identity(),before)
        (joint.APP_PLIST.parent/joint.EXECUTABLE).unlink()
        (joint.APP_PLIST.parent/joint.EXECUTABLE).symlink_to('/dev/null')
        with self.assertRaises(joint.CaptureFailed):joint.product_identity()

    def test_dedicated_workflow_and_existing_global_budgets_are_retained(self):
        root=Path(joint.__file__).resolve().parents[1]
        workflow=yaml.load((root/'.github/workflows/mini-passive-launch.yml').read_text(),Loader=yaml.BaseLoader)
        self.assertEqual(workflow['on'],{'push':{'branches':['codex/mini-passive-launch']}})
        self.assertEqual(workflow['permissions'],{'contents':'read'})
        self.assertEqual(set(workflow['jobs']),{'mini-passive-launch'})
        job=workflow['jobs']['mini-passive-launch']
        self.assertEqual(job['runs-on'],'xcode-27');self.assertEqual(job['timeout-minutes'],'20')
        self.assertEqual(job['env']['TOUCHCOLOR_EVIDENCE_LIMIT'],'1000000')
        self.assertEqual(workflow['concurrency']['cancel-in-progress'],'false')
        steps=job['steps'];runtime=next(x for x in steps if 'mini_passive_launch.py' in x.get('run',''))
        self.assertEqual(runtime['run'],'python3 scripts/mini_passive_launch.py launch-once')
        position=steps.index(runtime)
        self.assertTrue(all('simctl' not in x.get('run','') and 'xcodebuild' not in x.get('run','')
                            for x in steps[position+1:]))
        for name in ('ios.yml','apple-platforms.yml','mini-passive-compatibility.yml'):
            value=yaml.load((root/'.github/workflows'/name).read_text(),Loader=yaml.BaseLoader)
            self.assertNotIn('codex/mini-passive-launch',value['on']['push']['branches'])

    def test_generated_record_passes_the_reviewed_actual512_byte_writer_guard(self):
        receipt=self.run_capture();writes=[]
        with patch.object(joint,'_write_nonblocking',wraps=console._write_nonblocking), \
             patch.object(console.os,'fstat',return_value=types.SimpleNamespace(st_mode=stat.S_IFIFO)), \
             patch.object(console.os,'fpathconf',return_value=512), \
             patch.object(console.os,'get_blocking',return_value=True), \
             patch.object(console.os,'set_blocking'), \
             patch.object(console.os,'write',side_effect=lambda fd,data:writes.append(data) or len(data)):
            self.assertTrue(joint.emit_joint_summary(receipt))
        self.assertEqual(len(writes),1);self.assertLessEqual(len(writes[0]),512)

    def test_existing_post_read_deadline_accounting_is_reused_byte_for_byte(self):
        self.assertIs(joint.JointCapture._drain,compatibility.CompatibilityCapture._drain)
        self.assertIs(joint.JointCapture._persist,compatibility.CompatibilityCapture._persist)


class RealOwnedPipeTests(unittest.TestCase):
    def test_real_two_processes_exit_under_one_owner_without_simulator_actions(self):
        with tempfile.TemporaryDirectory() as directory:
            old=Path.cwd();os.chdir(directory)
            try:
                started=time.monotonic()
                clock=lambda:time.monotonic()
                budget=base.Budget(clock);budget.deadline=started+600
                budget.record={**budget.record,'lane':'mini-passive-launch','minutes':20}
                warmup=joint.Warmup('iPadMini',started=started,budget=budget)
                identity={'family':'iPadMini','udid':base.UUID,'runtime':base.RUNTIME,'started':1}
                Path('build/iPadMini-simulator.json').write_text(json.dumps(identity))
                joint.APP_PLIST.parent.mkdir(parents=True)
                import plistlib
                joint.APP_PLIST.write_bytes(plistlib.dumps({'CFBundleIdentifier':joint.APP,'CFBundleExecutable':joint.EXECUTABLE}))
                (joint.APP_PLIST.parent/joint.EXECUTABLE).write_bytes(b'synthetic product code')
                warmup.mini_joint_identity = identity
                warmup.mini_joint_product = joint.product_identity()
                env={'GITHUB_SHA':'a'*40,'GITHUB_WORKFLOW_SHA':'a'*40,'GITHUB_RUN_ID':'123','GITHUB_RUN_ATTEMPT':'1',
                     'GITHUB_ACTIONS':'true','RUNNER_OS':'macOS','RUNNER_ENVIRONMENT':'github-hosted','GITHUB_JOB':'mini-passive-launch',
                     'GITHUB_REPOSITORY':'100mango/ColorPicker','GITHUB_REF':joint.REF,'GITHUB_EVENT_NAME':'push',
                     'GITHUB_WORKFLOW_REF':joint.WORKFLOW}
                seen=[]
                def local_process(argv,**kwargs):
                    seen.append(argv)
                    program='import time; print("synthetic stream",flush=True); time.sleep(4)' if argv[2]=='spawn' else 'print("synthetic launch exit")'
                    return REAL_POPEN([sys.executable,'-c',program],**kwargs)
                with patch.dict(os.environ,env),patch.object(joint.subprocess,'Popen',side_effect=local_process), \
                     patch.object(joint,'_write_nonblocking',return_value=False):
                    receipt=joint.JointCapture(warmup,preparation_started=started).run()
                self.assertEqual(len(seen),2)
                self.assertTrue(receipt['host_cleanup_confirmed'])
                self.assertEqual(receipt['processes']['launcher']['observed_work_exit'],0)
                self.assertEqual(receipt['readiness'],'unknown')
                self.assertLess(time.monotonic()-started,5)
                self.assertTrue(warmup.pending.exists())
            finally:os.chdir(old)


if __name__ == '__main__':unittest.main()
