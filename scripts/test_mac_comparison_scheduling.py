"""Source-backed scheduling/fault traces, not native Swift/AppKit execution.

The portable model takes timing constants and property order from the actual
controller. Structural tests pin the guards and transition ordering that it
models; generated terminal receipts also pass the production Python validator.
This cannot validate Dispatch scheduling, AppKit, signing, or native compilation.
"""
import copy
from pathlib import Path
import re
import unittest

import mac_launch_comparison as m
from test_mac_launch_comparison import Clock, PRODUCT, SOURCE, control, request


SOURCE_PATH = Path(__file__).resolve().parent / 'MacLaunchComparison.swift'
SWIFT = SOURCE_PATH.read_text()


def body(name, next_name):
    return SWIFT.split('private func ' + name + '(', 1)[1].split('private func ' + next_name + '(', 1)[0]


VERIFY = body('verify', 'verifyProduct')
CALLBACK = body('completed', 'terminateOwned')
TIMER = body('terminateOwned', 'pollTermination')
FAILURE = body('fail', 'live')
PROPERTIES = tuple(re.findall(r'let \w+ = app\.(\w+)\n', VERIFY))
OBSERVATION = float(re.search(r'observationDeadline = callback \+ ([\d.]+)', CALLBACK)[1])
SCHEDULE = float(re.search(r'observationScheduled = callback \+ ([\d.]+)', CALLBACK)[1])
RESERVE = float(re.search(r'terminationDeadline = min\(entered \+ ([\d.]+), deadline\)', TIMER)[1])


class Stopped(Exception):
    pass


class SyntheticController:
    """Only the fixed controller's callback, passive timer and owned cleanup.

    fault delays end exactly at the active deadline. A failed persistence may
    expose its candidate first, as a successful rename followed by failed fsync
    can. Failure recovery must replace that claim or remove the receipt.
    """
    def __init__(self, *, late=None, mismatch=None, persist_error=None,
                 persist_late=None, recovery_error=False, accepted=True):
        self.clock = Clock()
        self.receipt = copy.deepcopy(control())
        self.callback = self.receipt['callbackMonotonic']
        self.deadline = request()['deadlineMonotonic']
        self.clock.value = self.callback
        self.stage = 'callback'
        self.trace = [('app', 'launch', 'preflight')]
        self.fence_index = None
        self.output = None
        self.owned_pid = self.receipt['identity']['pid']
        self.late = late
        self.mismatch = mismatch
        self.persist_error = persist_error
        self.persist_late = persist_late
        self.recovery_error = recovery_error
        self.accepted = accepted
        for field in ('terminated', 'terminatedMonotonic', 'finished', 'finishedMonotonic',
                      'terminationRequested', 'terminationRequestedMonotonic', 'terminationDeadlineMonotonic',
                      'observationEnteredMonotonic', 'observationLatenessSeconds', 'observationComplete',
                      'cleanupStartedMonotonic'):
            self.receipt[field] = None
        self.receipt.update(schema=2, status='unavailable', reason='not-started',
                            launchRequests=1, terminateRequests=0, cleanupConfirmed=False,
                            operationUncertain=False)
        try:
            self.verify('callback', self.receipt['callbackDeadlineMonotonic'])
            # An independently completed callback establishes ownership first.
            self.receipt['callbackMonotonic'] = self.clock()
            self.callback = self.clock()
            self.receipt['observationDeadlineMonotonic'] = self.callback + OBSERVATION
            self.receipt['observationScheduledMonotonic'] = self.callback + SCHEDULE
            self.stage = 'observing'
            self.persist('callback', self.callback + OBSERVATION)
            self.live(self.callback + OBSERVATION)
        except Stopped:
            pass

    def fail(self, reason):
        self.stage = 'stopped'
        self.receipt.update(status='unavailable', reason=reason, operationUncertain=True,
                            cleanupConfirmed=False if self.receipt['terminateRequests'] == 0 else None,
                            finished=self.clock(), finishedMonotonic=self.clock())
        self.fence_index = len(self.trace)
        self.trace.append(('local', 'durable-fence'))
        if self.recovery_error:
            self.trace.extend([('local', 'failure-persist-error'), ('local', 'remove-stale-receipt')])
            self.output = None
        else:
            self.trace.append(('local', 'failure-persist'))
            self.output = copy.deepcopy(self.receipt)
        raise Stopped(reason)

    def live(self, until):
        if self.fence_index is not None or self.clock() >= min(until, self.deadline):
            self.fail('deadline-or-uncertainty-fence')

    def app_call(self, name, phase, until):
        self.live(until)
        self.trace.append(('app', name, phase))
        if self.late == (phase, name):
            self.clock.value = min(until, self.deadline)
        self.live(until)

    def verify(self, phase, until):
        for name in PROPERTIES:
            self.app_call(name, phase, until)
            if self.mismatch == name:
                self.fail('termination-identity-unavailable')
        self.trace.append(('local', 'product-revalidation', phase))
        if self.late == (phase, 'product'):
            self.clock.value = min(until, self.deadline)
        if self.mismatch == 'product':
            self.fail('termination-identity-unavailable')
        self.live(until)

    def persist(self, phase, until):
        self.trace.append(('local', 'persist', phase))
        self.output = copy.deepcopy(self.receipt)
        if self.persist_late == phase:
            self.clock.value = min(until, self.deadline)
        if self.persist_error == phase:
            self.fail('completion-persistence-unavailable' if phase == 'completion' else 'persistence-unavailable')

    def enter(self, offset):
        if self.stage != 'observing':
            return
        self.clock.value = self.callback + offset
        entered = self.clock()
        ceiling = self.receipt['observationDeadlineMonotonic']
        self.receipt.update(observationEnteredMonotonic=entered,
                            observationLatenessSeconds=max(0, entered - self.receipt['observationScheduledMonotonic']),
                            observationComplete=entered < ceiling)
        try:
            self.live(self.deadline)
            if self.owned_pid is None or self.owned_pid <= 0 or not isinstance(self.receipt['identity'], dict):
                self.fail('cleanup-identity-missing')
            until = min(entered + RESERVE, self.deadline)
            self.receipt.update(cleanupStartedMonotonic=entered, terminationDeadlineMonotonic=until,
                                status='incomplete', reason='cleanup-pending' if entered < ceiling else 'observation-scheduling-miss')
            self.stage = 'cleaning-up'
            self.persist('cleanup-start', until)
            self.live(until)
            self.verify('cleaning-up', until)
            self.live(until)
            self.receipt.update(terminateRequests=1, terminationRequested=self.clock(),
                                terminationRequestedMonotonic=self.clock())
            self.persist('termination-request', until)
            self.live(until)
            self.stage = 'terminating'
            self.app_call('terminate', 'terminating', until)
            if not self.accepted:
                self.fail('termination-not-accepted')
            self.app_call('isTerminated', 'terminating', until)
            self.stage = 'finalizing'
            complete = self.receipt['observationComplete'] and not self.receipt['operationUncertain']
            self.receipt.update(terminated=self.clock(), terminatedMonotonic=self.clock(), cleanupConfirmed=True,
                                status='completed' if complete else 'incomplete',
                                reason='process-launch-only-not-window-readiness' if complete else 'observation-scheduling-miss',
                                finished=self.clock(), finishedMonotonic=self.clock())
            self.persist('completion', until)
            self.live(until)
            self.stage = 'stopped'
        except Stopped:
            pass


class SwiftSchedulingSourceTests(unittest.TestCase):
    def test_exact_schema_and_existing_ceilings(self):
        initial = SWIFT.split('receipt = [', 1)[1].split('\n    }', 1)[0]
        keys = re.findall(r'"([A-Za-z][A-Za-z0-9]*)":', initial)
        self.assertEqual(len(keys), 34)
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(set(keys), set(control()))
        self.assertIn('"schema": 2', initial)
        self.assertEqual((SCHEDULE, OBSERVATION, RESERVE), (10.5, 12, 20))
        self.assertIn('deadline <= began + 92', SWIFT)
        self.assertIn('callbackDeadline = min(began + 60, deadline - 32)', SWIFT)
        self.assertEqual(m.CONTROL, 92)
        self.assertEqual(m.CLEANUP, 20)

    def test_callback_capture_and_timer_entry_order(self):
        self.assertLess(CALLBACK.index('try verify(app,'), CALLBACK.index('let callback = now()'))
        self.assertLess(CALLBACK.index('let callback = now()'), CALLBACK.index('observationDeadline = callback + 12'))
        self.assertIn('receipt["callbackMonotonic"] = callback', CALLBACK)
        self.assertIn('let observationDelay = max(0, observationScheduled - now())', CALLBACK)
        self.assertEqual(CALLBACK.count('DispatchQueue.main.asyncAfter('), 1)
        self.assertIn('deadline: .now() + observationDelay', CALLBACK)
        self.assertLess(TIMER.index('let entered = now()'), TIMER.index('guard live("observing", until: deadline)'))
        self.assertIn('receipt["observationComplete"] = entered < observationDeadline', TIMER)
        self.assertIn('receipt["observationLatenessSeconds"] = max(0, entered - observationScheduled)', TIMER)
        self.assertLess(TIMER.index('guard let app = owned, let expectedPID = ownedPID'), TIMER.index('stage = "cleaning-up"'))
        self.assertLess(TIMER.index('try persist()'), TIMER.index('try verify(app,'))
        self.assertIn('expectedPID: expectedPID', TIMER)
        self.assertNotIn('until: observationDeadline', TIMER)

    def test_each_identity_read_has_immediate_pre_and_post_guards(self):
        self.assertEqual(PROPERTIES, ('processIdentifier', 'bundleIdentifier', 'bundleURL', 'executableURL', 'isTerminated'))
        for name in PROPERTIES:
            before, after = VERIFY.split('app.' + name, 1)
            with self.subTest(property=name):
                self.assertRegex(before, r'guard live\(expected, until: until\) else \{ throw Invalid.contract \}\n        let \w+ = $')
                self.assertTrue(after.startswith('\n        guard live(expected, until: until)'))
        for check, next_read in [('pid == expectedPID', 'app.bundleIdentifier'), ('identifier == bundleID', 'app.bundleURL'),
                                 ('url.resolvingSymlinksInPath().path == path', 'app.executableURL'),
                                 ('actualExecutable.resolvingSymlinksInPath().path == executable', 'app.isTerminated')]:
            self.assertLess(VERIFY.index(check), VERIFY.index(next_read))
        self.assertIn('try verifyProduct()\n        guard live(expected, until: until)', VERIFY)

    def test_failure_path_is_local_and_invalidates_terminal_claim(self):
        for forbidden in ('NSRunningApplication.', 'owned.', 'terminate()', 'NSWorkspace.'):
            self.assertNotIn(forbidden, FAILURE)
        self.assertLess(FAILURE.index('try atomic(fence'), FAILURE.index('try persist()'))
        self.assertIn('receipt["operationUncertain"] = true', FAILURE)
        self.assertIn('receipt["status"] = "unavailable"', FAILURE)
        self.assertIn('receipt["cleanupConfirmed"] = NSNull()', FAILURE)
        self.assertIn('_ = unlink(output.path)', FAILURE)
        poll = SWIFT.split('private func pollTermination()', 1)[1]
        self.assertLess(poll.index('stage = "finalizing"'), poll.index('try persist()'))
        self.assertLess(poll.index('fail("completion-persistence-late-or-fenced")'), poll.index('stage = "stopped"'))
        self.assertIn('receipt["observationComplete"] as? Bool == true && receipt["operationUncertain"] as? Bool == false', poll)
        self.assertIn('receipt["status"] = complete ? "completed" : "incomplete"', poll)
        self.assertIn('"observation-scheduling-miss"', poll)

    def test_no_additional_operation_or_runtime_layer(self):
        self.assertEqual(SWIFT.count('NSWorkspace.shared.openApplication('), 1)
        self.assertEqual(SWIFT.count('app.terminate()'), 1)
        self.assertEqual(re.findall(r'^import (\w+)$', SWIFT, re.M), ['AppKit', 'CryptoKit', 'Darwin', 'Security'])
        for forbidden in ('forceTerminate', 'activate(', 'AXUIElement', 'openWindow', 'screenshot', 'removePersistentDomain'):
            self.assertNotIn(forbidden, SWIFT)


class SyntheticSchedulingTests(unittest.TestCase):
    def assert_trace_safe(self, model):
        app = [event for event in model.trace if event[0] == 'app']
        self.assertEqual(sum(event[1] == 'launch' for event in app), 1)
        self.assertLessEqual(sum(event[1] == 'terminate' for event in app), 1)
        if model.fence_index is not None:
            self.assertFalse(any(event[0] == 'app' for event in model.trace[model.fence_index:]))
            self.assertTrue(model.receipt['operationUncertain'])
            self.assertEqual(model.receipt['status'], 'unavailable')
            self.assertIsNot(model.receipt['cleanupConfirmed'], True)
        before = copy.deepcopy(model.trace)
        model.enter(90)  # No duplicate timer may reopen cleanup or cross a fence.
        self.assertEqual(model.trace, before)

    def validate(self, model, *, allow_incomplete=True):
        return m.validate_control(m.encode(model.output), m.encode(request()), SOURCE, PRODUCT, 'd' * 64,
                                  allow_incomplete=allow_incomplete)

    def test_timely_and_late_passive_timers_keep_separate_completion(self):
        for offset in (10.5, 11.9, 12.0, 12.6):
            with self.subTest(offset=offset):
                model = SyntheticController()
                verified = model.callback
                model.enter(offset)
                r = model.receipt
                self.assertEqual(r['callbackMonotonic'], verified)
                self.assertLess(verified, r['observationEnteredMonotonic'])
                self.assertEqual(r['observationComplete'], offset < 12)
                self.assertAlmostEqual(r['observationLatenessSeconds'], offset - 10.5)
                self.assertEqual(r['cleanupStartedMonotonic'], verified + offset)
                self.assertEqual(r['terminationDeadlineMonotonic'], min(verified + offset + 20, model.deadline))
                self.assertTrue(r['cleanupConfirmed'])
                self.assertFalse(r['operationUncertain'])
                self.assertEqual(r['status'], 'completed' if offset < 12 else 'incomplete')
                self.assertEqual(r['terminateRequests'], 1)
                if offset >= 12:
                    self.assertEqual(r['reason'], 'observation-scheduling-miss')
                validated = self.validate(model)
                self.assertEqual(m.comparison_complete(validated['completion']), offset < 12)
                if offset >= 12:
                    with self.assertRaises(ValueError):
                        self.validate(model, allow_incomplete=False)
                else:
                    self.validate(model, allow_incomplete=False)
                self.assert_trace_safe(model)

    def test_every_late_cleanup_property_stops_before_the_next_app_call(self):
        for name in PROPERTIES + ('product',):
            with self.subTest(property=name):
                model = SyntheticController(late=('cleaning-up', name))
                model.enter(12.6)
                cleanup = [e[1] for e in model.trace if e[0] == 'app' and e[2] == 'cleaning-up']
                self.assertEqual(cleanup, list(PROPERTIES if name == 'product' else PROPERTIES[:PROPERTIES.index(name) + 1]))
                self.assertEqual(model.receipt['terminateRequests'], 0)
                self.assertFalse(model.receipt['observationComplete'])
                self.assertFalse(m.comparison_complete(self.validate(model)['completion']))
                self.assert_trace_safe(model)

    def test_late_callback_identity_never_enters_owned_cleanup(self):
        for name in PROPERTIES + ('product',):
            with self.subTest(property=name):
                model = SyntheticController(late=('callback', name))
                model.enter(12.6)
                self.assertIsNone(model.receipt['cleanupStartedMonotonic'])
                self.assertEqual(model.receipt['terminateRequests'], 0)
                self.assert_trace_safe(model)

    def test_missing_owned_identity_never_starts_cleanup(self):
        for field, value in (('owned_pid', None), ('owned_pid', 0), ('owned_pid', -1), ('identity', None)):
            with self.subTest(field=field, value=value):
                model = SyntheticController()
                if field == 'owned_pid':
                    model.owned_pid = value
                else:
                    model.receipt['identity'] = value
                model.enter(12.6)
                self.assertIsNone(model.receipt['cleanupStartedMonotonic'])
                self.assertFalse(any(e[0] == 'app' and e[2] != 'callback' and e[1] != 'launch' for e in model.trace))
                self.assert_trace_safe(model)

    def test_changed_cleanup_identity_stops_on_the_changed_property(self):
        for name in PROPERTIES + ('product',):
            with self.subTest(property=name):
                model = SyntheticController()
                model.mismatch = name
                model.enter(12.6)
                self.assertEqual(model.receipt['terminateRequests'], 0)
                self.assertFalse(any(e[:2] == ('app', 'terminate') for e in model.trace))
                self.assertFalse(m.comparison_complete(self.validate(model)['completion']))
                self.assert_trace_safe(model)

    def test_expired_global_ceiling_never_calls_owned_app(self):
        model = SyntheticController()
        before = [e for e in model.trace if e[0] == 'app']
        model.enter(model.deadline - model.callback)
        self.assertEqual([e for e in model.trace if e[0] == 'app'], before)
        self.assertIsNone(model.receipt['cleanupStartedMonotonic'])
        self.assertFalse(model.receipt['observationComplete'])
        self.assertFalse(m.comparison_complete(self.validate(model)['completion']))
        self.assert_trace_safe(model)

    def test_cleanup_reserve_is_clipped_to_original_ceiling(self):
        model = SyntheticController()
        model.enter(model.deadline - model.callback - 2)
        self.assertEqual(model.receipt['terminationDeadlineMonotonic'], model.deadline)
        self.assertEqual(model.receipt['status'], 'incomplete')
        self.assertTrue(model.receipt['cleanupConfirmed'])
        self.assertFalse(m.comparison_complete(self.validate(model)['completion']))
        self.assert_trace_safe(model)

    def test_late_termination_and_poll_never_issue_another_app_call(self):
        for operation in ('terminate', 'isTerminated'):
            with self.subTest(operation=operation):
                model = SyntheticController(late=('terminating', operation))
                model.enter(12.6)
                calls = [e[1] for e in model.trace if e[0] == 'app' and e[2] == 'terminating']
                self.assertEqual(calls, ['terminate'] if operation == 'terminate' else ['terminate', 'isTerminated'])
                self.assertIsNone(model.receipt['cleanupConfirmed'])
                self.assertFalse(m.comparison_complete(self.validate(model)['completion']))
                self.assert_trace_safe(model)

    def test_rejected_termination_is_fenced_before_poll(self):
        model = SyntheticController(accepted=False)
        model.enter(12.6)
        self.assertEqual([e[1] for e in model.trace if e[0] == 'app' and e[2] == 'terminating'], ['terminate'])
        self.assertFalse(m.comparison_complete(self.validate(model)['completion']))
        self.assert_trace_safe(model)

    def test_every_failed_or_late_persistence_fences_without_app_recovery(self):
        for phase in ('callback', 'cleanup-start', 'termination-request', 'completion'):
            for fault in ('persist_error', 'persist_late'):
                with self.subTest(phase=phase, fault=fault):
                    model = SyntheticController(**{fault: phase})
                    model.enter(12.6)
                    self.assertEqual(model.output['status'], 'unavailable')
                    self.assertTrue(model.output['operationUncertain'])
                    self.assertIsNot(model.output['cleanupConfirmed'], True)
                    self.assertFalse(m.comparison_complete(self.validate(model)['completion']))
                    self.assert_trace_safe(model)

    def test_failed_terminal_recovery_removes_visible_success(self):
        for offset in (10.5, 12.6):
            for fault in ('persist_error', 'persist_late'):
                with self.subTest(offset=offset, fault=fault):
                    model = SyntheticController(**{fault: 'completion'}, recovery_error=True)
                    model.enter(offset)
                    self.assertIsNone(model.output)
                    self.assertIn(('local', 'remove-stale-receipt'), model.trace)
                    self.assert_trace_safe(model)


if __name__ == '__main__':
    unittest.main()
