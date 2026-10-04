"""No Apple execution: failure and coordination checks for the real-pair harness."""
import json
import hashlib
import copy
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import test_paired_watch as harness


class PairedHarnessTests(unittest.TestCase):
    def setUp(self):
        harness.report.clear()
        harness.report.update(result='passed', stages=[], receipt_barrier='acknowledged')

    def process(self, role):
        return SimpleNamespace(markers=['TOUCHCOLOR_PAIRED_'+role.upper()+'_RELAUNCH_VERIFIED'], cleanup_confirmed=True)

    def test_failed_exit_missing_marker_and_unclean_group_reject(self):
        phone, watch = self.process('phone'), self.process('watch')
        harness.validate_outcome(phone, watch, 0, 0)
        with self.assertRaises(RuntimeError): harness.validate_outcome(phone, watch, 65, 0)
        phone.markers=[]
        with self.assertRaises(RuntimeError): harness.validate_outcome(phone, watch, 0, 0)
        phone.markers=['TOUCHCOLOR_PAIRED_PHONE_RELAUNCH_VERIFIED']; watch.cleanup_confirmed=False
        with self.assertRaises(RuntimeError): harness.validate_outcome(phone, watch, 0, 0)

    def test_cleanup_failures_cannot_retain_passed_result(self):
        with patch.object(harness, 'run', side_effect=RuntimeError('synthetic owned delete failure')):
            self.assertFalse(harness.cleanup({}, [], None, {}, {}, {}, []))
        self.assertEqual(harness.report['result'],'failed')

    def test_original_pair_cannot_be_activated_or_cleaned_as_owned(self):
        # verify_pair is required before activation and again before unpair.
        with self.assertRaises(ValueError):
            harness.verify_pair({'pairs':{'old':{'phone':{'udid':'p'},'watch':{'udid':'w'}}}},'old','w','p',{'old':{}})

    def test_generated_target_environment_is_exact_and_linked(self):
        with tempfile.TemporaryDirectory() as folder:
            product=Path(folder)/'Build/Products'; product.mkdir(parents=True)
            path=product/'observed.xctestrun'
            path.write_bytes(plistlib.dumps({'UITests':{'TestBundlePath':'__TESTROOT__/TouchColorUITests.xctest','TestHostPath':'__TESTROOT__/Runner.app','UITargetAppPath':'__TESTROOT__/Debug-iphonesimulator/TouchColor.app','IsUITestBundle':True}}))
            out=harness.configured_test_run(folder,'phone','synthetic-run')
            actual=plistlib.loads(out.read_bytes())['UITests']
            self.assertEqual(actual['EnvironmentVariables'],{'TOUCHCOLOR_PAIRED_E2E':'1','TOUCHCOLOR_PAIRED_RUN_ID':'synthetic-run'})
            self.assertEqual(actual['UITargetAppPath'],'__TESTROOT__/Debug-iphonesimulator/TouchColor.app')
            path.write_bytes(plistlib.dumps({'wrong':{'TestBundlePath':'Other.xctest'}}))
            with self.assertRaises(RuntimeError): harness.configured_test_run(folder,'phone','synthetic-run')

    def test_receipts_must_match_payload_protocol_uuid_and_foreground_channel(self):
        identifier='12345678-1234-1234-1234-123456789ABC'
        digest=hashlib.sha256(json.dumps({'version':1,'id':identifier,'colors':['#fe0000']},sort_keys=True,separators=(',',':')).encode()).hexdigest()
        values={role:{'role':role,'runID':'run','requestID':identifier,'requestProtocol':'touchColorPaletteV1','receiptProtocol':'touchColorReceiptV1','version':'1','outcome':'accepted','receiveChannel':'sendMessage','fingerprint':digest} for role in ('phone','watch')}
        self.assertEqual(harness.validate_receipt_observations(values,'run'),(identifier,digest))
        for key,bad in [('requestID','other'),('requestProtocol','other'),('receiptProtocol','other'),('version','2'),('outcome','rejected'),('receiveChannel','transferUserInfo'),('fingerprint','0'*64)]:
            changed=copy.deepcopy(values);changed['watch'][key]=bad
            with self.assertRaises(RuntimeError,msg=key):harness.validate_receipt_observations(changed,'run')
        changed=copy.deepcopy(values)
        for value in changed.values():value['fingerprint']='0'*64
        with self.assertRaises(RuntimeError):harness.validate_receipt_observations(changed,'run')

    def test_installed_record_includes_debug_dylib_not_only_launcher(self):
        with tempfile.TemporaryDirectory() as folder:
            app=Path(folder)/'TouchColor.app';app.mkdir()
            (app/'Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':'com.mango.touchColor.watchkitapp','CFBundleExecutable':'TouchColor','CFBundleShortVersionString':'2.0','CFBundleVersion':'20001','CFBundleSupportedPlatforms':['WatchSimulator'],'WKCompanionAppBundleIdentifier':'com.mango.touchColor'}))
            (app/'TouchColor').write_bytes(b'fixed launcher');(app/'TouchColor.debug.dylib').write_bytes(b'first actual implementation')
            before=harness.product_record(app,'watch')
            (app/'TouchColor.debug.dylib').write_bytes(b'changed actual implementation')
            self.assertNotEqual(before,harness.product_record(app,'watch'))

    def test_actual_summary_requires_one_non_skipped_case_on_the_owned_destination(self):
        counts={'passedTests':1,'failedTests':0,'skippedTests':0,'expectedFailures':0}
        row={**counts,'device':{'deviceId':'owned','platform':'watchOS Simulator','osVersion':'27.0','architecture':'arm64'}}
        value={**counts,'result':'Passed','totalTestCount':1,'devicesAndConfigurations':[row],'testFailures':[]}
        self.assertEqual(harness.verify_result_summary(value,'owned','watch')['totalTestCount'],1)
        for key,bad in [('totalTestCount',0),('skippedTests',1),('expectedFailures',1),('passedTests',2),('result','Skipped')]:
            changed=copy.deepcopy(value);changed[key]=bad
            with self.assertRaises(RuntimeError,msg=key):harness.verify_result_summary(changed,'owned','watch')
        changed=copy.deepcopy(value);changed['devicesAndConfigurations'][0]['device']['deviceId']='clone'
        with self.assertRaises(RuntimeError):harness.verify_result_summary(changed,'owned','watch')

    def test_optimized_python_keeps_failed_exit_and_cleanup_gates(self):
        code='''
from types import SimpleNamespace
from unittest.mock import patch
import test_paired_watch as h
p=SimpleNamespace(markers=['TOUCHCOLOR_PAIRED_PHONE_RELAUNCH_VERIFIED'],cleanup_confirmed=True)
w=SimpleNamespace(markers=['TOUCHCOLOR_PAIRED_WATCH_RELAUNCH_VERIFIED'],cleanup_confirmed=True)
h.report.update(result='passed',stages=[],receipt_barrier='acknowledged')
try: h.validate_outcome(p,w,65,0)
except RuntimeError: pass
else: raise SystemExit('optimized interpreter accepted failed XCTest')
with patch.object(h,'run',side_effect=RuntimeError('owned unpair/delete failure')):
    if h.cleanup({},[],None,{},{},{},[]): raise SystemExit('accepted failed cleanup')
if h.report['result']!='failed': raise SystemExit('failed cleanup retained passed result')
try: h.require(False,'readiness missing')
except RuntimeError: pass
else: raise SystemExit('optimized interpreter removed readiness gate')
try: h.verify_result_summary({'result':'Passed','totalTestCount':0},'owned','phone')
except RuntimeError: pass
else: raise SystemExit('optimized interpreter accepted zero executed tests')
'''
        result=subprocess.run([sys.executable,'-O','-c',code],cwd=Path(__file__).parent,env={**os.environ,'PYTHONOPTIMIZE':'1'},capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

if __name__=='__main__': unittest.main()
