import hashlib
import json
from pathlib import Path
import unittest
from watch_heartbeat_evidence import CASE, LOG_CAP, UI_CAP, REPORT_CAP, summarize
ROOT=Path(__file__).resolve().parents[1]
NONCE='F2D612CA-E494-43B8-974B-7918672C9DEB'
SCOPE=('WATCH_MAIN_ACTOR_SCOPE nonce='+NONCE+'\n').encode()
def event(name='baseline',seq=0,ms=0,pid=11096,nonce=NONCE,process='TouchColor',case=CASE):
    return f'2026-10-08 09:00:00.123 Df {process}[{pid}:9ded] [com.mango.touchColor.WatchDiagnostics:editor] WATCH_MAIN_ACTOR event={name} case={case} nonce={nonce} seq={seq} elapsed_ms={ms}\n'.encode()
class EvidenceTests(unittest.TestCase):
    def test_baseline_without_copy_is_not_deadlock(self):
        r=summarize(SCOPE,event()+event(seq=1,ms=2000));self.assertEqual(r['baseline_samples'],2)
        self.assertFalse(r['copy_action_enter_observed']);self.assertFalse(r['deadlock_established'])
    def test_action_enter_without_exit_remains_observation_only(self):
        r=summarize(SCOPE,event()+event('copy_enter'));self.assertTrue(r['copy_action_enter_observed'])
        self.assertFalse(r['copy_action_exit_observed']);self.assertFalse(r['deadlock_established'])
    def test_copy_beats_show_sampled_scheduling_not_product_pass(self):
        r=summarize(SCOPE,event()+event('copy_enter')+event('copy_exit',ms=3)+event('copy_beat',1,2000)+event('copy_beat',2,4000))
        self.assertEqual(r['copy_mainactor_samples'],2);self.assertEqual(r['pid'],11096)
        self.assertEqual(r['pid_provenance'],'OSLog compact process header');self.assertFalse(r['product_qualified'])
    def test_missing_enter_with_present_beat_does_not_invent_enter(self):
        r=summarize(SCOPE,event('copy_beat',1,2000));self.assertEqual(r['copy_mainactor_samples'],1)
        self.assertFalse(r['copy_action_enter_observed'])
    def test_no_events_is_not_observed(self):
        r=summarize(SCOPE,b'');self.assertEqual(r['state'],'not-observed');self.assertIsNone(r['pid'])
    def test_missing_or_duplicate_scope_never_qualifies(self):
        for scope in (b'',SCOPE+SCOPE):self.assertEqual(summarize(scope,event())['state'],'not-observed')
    def test_foreign_nonce_case_and_runner_ignored(self):
        for output in (event(nonce='A'*36),event(process='TouchColorWatchUITests-Runner'),event(case='OtherCase')):
            self.assertEqual(summarize(SCOPE,output)['state'],'not-observed')
    def test_message_self_reported_pid_not_accepted(self):
        self.assertEqual(summarize(SCOPE,b'WATCH_MAIN_ACTOR pid=11096 '+event())['state'],'not-observed')
    def test_two_app_pids_rejected(self):
        r=summarize(SCOPE,event()+event(seq=1,ms=2000,pid=11097));self.assertEqual(r['reason'],'multiple-target-processes')
    def test_duplicate_sequence_rejected(self):
        self.assertEqual(summarize(SCOPE,event()+event())['reason'],'duplicate-or-reversed-event')
    def test_reversed_elapsed_rejected(self):
        self.assertEqual(summarize(SCOPE,event(seq=1,ms=2000)+event(seq=2,ms=1000))['reason'],'duplicate-or-reversed-event')
    def test_bad_sequence_or_window_rejected(self):
        for value in (event(seq=6),event(ms=12001),event('copy_beat'),event('copy_beat',1,14001),event('copy_enter',1)):
            self.assertEqual(summarize(SCOPE,value)['reason'],'event-contract-mismatch')
    def test_invalid_encoding_or_input_size_rejected(self):
        self.assertEqual(summarize(SCOPE,b'\xff')['reason'],'unsupported-text-encoding')
        self.assertEqual(summarize(SCOPE,b'x'*(LOG_CAP+1))['reason'],'input-byte-limit')
        self.assertEqual(summarize(b'x'*(UI_CAP+1),b'')['reason'],'input-byte-limit')
    def test_maximum_fourteen_events_stays_compact(self):
        output=b''.join(event(seq=i,ms=i*2000) for i in range(6))+event('copy_enter')+event('copy_exit',ms=2)
        output+=b''.join(event('copy_beat',i,i*2000) for i in range(1,7))
        r=summarize(SCOPE,output);self.assertEqual(len(r['events']),14);self.assertLess(len(json.dumps(r,indent=2).encode()),REPORT_CAP)
    def test_unknown_text_and_secrets_never_retained(self):
        secret='UNRELATED_PRIVATE_TEST_STRING';r=summarize(SCOPE,(secret+'\n').encode()+event())
        self.assertNotIn(secret,json.dumps(r))
class SourceContractTests(unittest.TestCase):
    def setUp(self):
        self.views=(ROOT/'TouchColorWatch/WatchViews.swift').read_text()
        self.tests=(ROOT/'TouchColorWatchUITests/WatchWorkflowTests.swift').read_text()
        self.members=self.views.split('@MainActor private enum WatchEditorDiagnostics {\n',1)[1].split('\n    private static var visibleEditors',1)[0]
    def test_instrumentation_is_inside_existing_debug_mainactor_enum(self):
        self.assertIn('#if DEBUG\n/// Bounded local lifecycle',self.views)
        self.assertIn('@MainActor private enum WatchEditorDiagnostics {\n'+self.members,self.views)
        self.assertIn('Task { @MainActor in',self.members)
        self.assertNotIn('Thread.sleep',self.members);self.assertNotIn('while ',self.members)
    def test_two_finite_windows_and_fourteen_records(self):
        self.assertIn('probeCount < 14',self.members)
        self.assertIn('probePulses("baseline", count: 5, started: started, window: 12)',self.members)
        self.assertIn('probePulses("copy_beat", count: 6, started: started, window: 14)',self.members)
        self.assertIn('now - birth <= 134',self.members);self.assertIn('systemUptime - birth <= 120',self.members)
        self.assertIn('!baselineStarted',self.members);self.assertIn('copyStarted == nil',self.members)
    def test_release_preprocessing_excludes_all_probe_definitions_and_calls(self):
        active=[True];branches=[];kept=[]
        for line in self.views.splitlines(True):
            token=line.strip()
            if token=='#if DEBUG':branches.append(active[-1]);active.append(False)
            elif token=='#else':active[-1]=branches[-1] and not active[-1]
            elif token=='#endif':active.pop();branches.pop()
            elif all(active):kept.append(line)
        release=''.join(kept)
        for marker in ('WATCH_MAIN_ACTOR','probeNonce','probeBaseline','probeCopyEnter','probeCopyExit','probePulses'):
            self.assertNotIn(marker,release)
    def test_no_ui_or_binding_write_in_probe(self):
        for forbidden in ('palette.','crownFocused','editingCopy','@State','@Published','FileManager','write(','asyncAfter','Timer','while '):
            self.assertNotIn(forbidden,self.members)
    def test_exact_case_opt_in_and_uuid_bound(self):
        self.assertIn('testCase == probeCase',self.members);self.assertIn('value.utf8.count == 36',self.members)
        self.assertIn('environment["TOUCHCOLOR_TEST_MAINACTOR_PROBE"] == "1"',self.members)
        self.assertIn('UUID(uuidString: value)?.uuidString',self.members)
    def test_removing_probe_restores_product_and_case_bytes(self):
        views=self.views.replace(self.members+'\n','',1)
        views=views.replace('''            .onAppear {
                #if DEBUG
                WatchEditorDiagnostics.probeBaseline()
                #endif
            }\n''','',1)
        views=views.replace('''                    #if DEBUG
                    WatchEditorDiagnostics.probeCopyEnter()
                    #endif
''','',1).replace('''                    #if DEBUG
                    WatchEditorDiagnostics.probeCopyExit()
                    #endif
''','',1)
        self.assertEqual(hashlib.sha256(views.encode()).hexdigest(),'77c51fc183bb460f81a12092093181089dbc0d62009d102a29ed75f6fd6575b3')
        setup='''            let probeNonce = UUID().uuidString
            app.launchEnvironment["TOUCHCOLOR_TEST_MAINACTOR_PROBE"] = "1"
            app.launchEnvironment["TOUCHCOLOR_TEST_MAINACTOR_NONCE"] = probeNonce
            print("WATCH_MAIN_ACTOR_SCOPE nonce=\\(probeNonce)")
'''
        self.assertEqual(hashlib.sha256(self.tests.replace(setup,'',1).encode()).hexdigest(),'0ba5074c16012fe9eb31af899eec607d95153f63f6660585b22a8ee9986f68d0')
if __name__=='__main__':unittest.main()
