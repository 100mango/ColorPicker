"""One fixed XCTest/NSWorkspace diagnostic. No canonical acceptance or app changes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import signal
import stat
import sys
import time
import uuid

from atomic_json import write_json
from job_budget import load as load_budget, BudgetExhausted, RESERVES, STARTUP_MARGIN
from palette_lifecycle_diagnostics import capture, CaptureStopped, valid_uuid
from retain_mac_evidence import strict_json, read_file
import mac_passive_lifecycle as passive

PLATFORM = 'mac-launch-comparison'
BRANCH = 'refs/heads/codex/mac-launch-comparison'
WORKFLOW = '.github/workflows/mac-launch-comparison.yml'
CASE = passive.CASES[0]
METHOD = 'TouchColorMacUITests/TouchColorMacUITests/' + CASE
ARGS = ['--ui-test-reset', '-AppleLanguages', '(en)', '-AppleLocale', 'en_US']
ROOT = Path('build/mac-launch-comparison')
EVIDENCE = Path('build/evidence')
STATE = ROOT / 'state.json'
LATCH = ROOT / 'uncertain.json'
REPORT = EVIDENCE / 'mac-launch-comparison.json'
CONTROLLER = ROOT / 'MacLaunchComparison'
RESULT = ROOT / 'contact.xcresult'
PREPARATION = 500
TEST = 300
CONTROL = 92
CLEANUP = 20
EVIDENCE_SECONDS = 180
LIMIT = 3_000_000
SOURCES = (WORKFLOW, 'scripts/MacLaunchComparison.swift', 'scripts/mac_launch_comparison.py',
    'scripts/job_budget.py', 'scripts/atomic_json.py', 'scripts/bounded_process.py',
    'scripts/palette_lifecycle_diagnostics.py', 'scripts/mac_passive_lifecycle.py',
    'scripts/retain_mac_evidence.py', 'TouchColorMacUITests/TouchColorMacUITests.swift',
    'TouchColorMac/TouchColorMacApp.swift', 'TouchColorMac.xcodeproj/project.pbxproj')
CONFOUNDERS = ['Fixed order: XCTest then NSWorkspace on one VM; not independently cold OS states.',
    'Original XCTest fixture/defaults teardown is unchanged; no saved-state deletion for NSWorkspace.',
    'XCTest instrumentation and inherited launch environment differ; requested arguments are the same.',
    'Declared signing entitlements are inspected; inherited sandbox state is not independently measured.',
    'Process launch is not window/contact readiness; observations do not qualify a release.']


def require(value, reason):
    if not value:
        raise ValueError(reason)


def digest(raw): return hashlib.sha256(raw).hexdigest()
def encode(value): return passive.encode(value)
def number(value): return passive.number(value)
def integer(value, low=0): return passive.integer(value, low)
def sha(value): return isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None


def durable(path, value, limit=128 * 1024):
    write_json(path, value, limit=limit)
    # atomic_json fsyncs the new file; also establish directory durability.
    descriptor = os.open(path.parent, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
    try: os.fsync(descriptor)
    finally: os.close(descriptor)


def source_identity(env):
    fixed = {'GITHUB_REPOSITORY': '100mango/ColorPicker', 'GITHUB_REF': BRANCH,
        'GITHUB_EVENT_NAME': 'push', 'GITHUB_WORKFLOW_REF': '100mango/ColorPicker/' + WORKFLOW + '@' + BRANCH,
        'TOUCHCOLOR_JOB_PLATFORM': PLATFORM, 'TOUCHCOLOR_JOB_MINUTES': '25',
        'TOUCHCOLOR_JOB_LANE': PLATFORM, 'TOUCHCOLOR_EVIDENCE_LIMIT': str(LIMIT)}
    require(all(env.get(k) == v for k, v in fixed.items()), 'wrong-dedicated-workflow')
    require(re.fullmatch('[0-9a-f]{40}', env.get('GITHUB_SHA', '')) and env.get('GITHUB_WORKFLOW_SHA') == env['GITHUB_SHA'], 'wrong-source')
    require(all(re.fullmatch('[1-9][0-9]{0,19}', env.get(k, '')) for k in ('GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT')), 'wrong-run')
    return {'repository': fixed['GITHUB_REPOSITORY'], 'ref': BRANCH, 'workflow': WORKFLOW,
        'workflow_ref': fixed['GITHUB_WORKFLOW_REF'], 'event': 'push', 'sha': env['GITHUB_SHA'],
        'run': env['GITHUB_RUN_ID'], 'attempt': env['GITHUB_RUN_ATTEMPT']}


def base_command():
    return ['xcodebuild', '-quiet', '-project', 'TouchColorMac.xcodeproj', '-scheme', 'TouchColorMac',
        '-configuration', 'Debug', '-destination', 'platform=macOS,arch=arm64',
        '-derivedDataPath', 'build/mac-tests', 'ARCHS=arm64', 'CODE_SIGNING_ALLOWED=NO']


def test_command():
    return base_command() + ['-resultBundlePath', str(RESULT), '-parallel-testing-enabled', 'NO',
        '-collect-test-diagnostics', 'never', '-test-timeouts-enabled', 'YES',
        '-maximum-test-execution-time-allowance', '120', '-only-testing:' + METHOD, 'test-without-building']


def product_identity():
    app = Path('build/mac-tests/Build/Products/Debug/TouchColor.app').absolute()
    require(app.resolve() == app and app.is_dir() and not app.is_symlink(), 'unsafe-product-path')
    metadata = plistlib.loads(read_file(app / 'Contents/Info.plist', 128 * 1024))
    require(metadata.get('CFBundleIdentifier') == 'com.mango.touchColor' and metadata.get('CFBundleExecutable') == 'TouchColor', 'wrong-product')
    executable = app / 'Contents/MacOS/TouchColor'
    logic = app / 'Contents/MacOS/TouchColor.debug.dylib'
    require(executable.resolve() == executable and logic.resolve() == logic, 'linked-product')
    return {'applicationPath': str(app), 'executable': str(executable),
        'executableSHA256': digest(read_file(executable, 16 * 1024 * 1024)),
        'logicSHA256': digest(read_file(logic, 16 * 1024 * 1024))}


def validate_caller(value, expected_hash):
    fields = {'inspection', 'entitlementsState', 'sandboxEnabled', 'inheritedSandbox', 'executableSHA256'}
    require(isinstance(value, dict) and set(value) == fields, 'unknown-caller-fields')
    require(value['inspection'] == 'validated-Security-signing-information' and
        value['entitlementsState'] in ('readable-dictionary', 'no-embedded-entitlements') and
        value['sandboxEnabled'] is False and value['inheritedSandbox'] == 'not-independently-measured' and
        value['executableSHA256'] == expected_hash, 'caller-not-declared-unsandboxed')
    return value


def validate_contact(root, product, command_exit):
    summary = strict_json(read_file(root / 'mac-ui-summary.json', 512 * 1024))
    require(isinstance(summary, dict), 'bad-contact-summary')
    for key in ('passedTests', 'failedTests', 'skippedTests', 'expectedFailures', 'totalTestCount'):
        require(integer(summary.get(key)), 'missing-case-count')
    require(summary['totalTestCount'] == 1 and summary['skippedTests'] == 0 and summary['expectedFailures'] == 0 and
        summary['passedTests'] + summary['failedTests'] == 1, 'not-exact-single-case')
    passed = summary['passedTests'] == 1
    require(summary.get('result') == ('Passed' if passed else 'Failed') and command_exit == (0 if passed else 65), 'contradictory-test-outcome')
    failures = summary.get('testFailures', [])
    require(isinstance(failures, list) and len(failures) == (0 if passed else 1), 'unknown-failure-count')
    for row in failures:
        require(isinstance(row, dict) and row.get('testIdentifierString') == 'TouchColorMacUITests/' + CASE + '()' and row.get('testIdentifierURL') == 'test://com.apple.xcode/TouchColorMac/TouchColorMacUITests/TouchColorMacUITests/' + CASE, 'foreign-failure')
        require(row.get('targetName')=='TouchColorMacUITests' and row.get('testName')==CASE+'()' and
            integer(row.get('testIdentifier'),1) and isinstance(row.get('failureText'),str) and
            re.match(r'^XCTAssert(?:True|Equal) failed(?: -|:)',row['failureText']), 'not-known-assertion-failure')
    configs=summary.get('devicesAndConfigurations')
    require(isinstance(configs,list) and len(configs)==1 and
        all(configs[0].get(k)==summary[k] and type(configs[0].get(k)) is int for k in ('passedTests','failedTests','skippedTests','expectedFailures')), 'contradictory-device-outcome')
    rows = passive.identities(root)
    require(len(rows) == 1 and rows[0]['case'] == CASE and rows[0]['ordinal'] == 1 and rows[0]['sandbox'] is False, 'missing-exact-receipt')
    identity = rows[0]
    require(all(identity[k] == v for k, v in product.items()), 'contact-product-mismatch')
    groups = strict_json(read_file(root / 'screenshots/manifest.json', 512 * 1024))
    require(len(groups) == 1 and groups[0]['testIdentifier'] == 'TouchColorMacUITests/' + CASE + '()', 'foreign-export-case')
    return {'outcome': 'passed' if passed else 'failed', 'identity': identity,
        'summarySHA256': digest(read_file(root / 'mac-ui-summary.json', 512 * 1024)),
        'manifestSHA256': digest(read_file(root / 'screenshots/manifest.json', 512 * 1024))}


def validate_control(raw, request_raw, source, product, controller_hash):
    value = strict_json(raw); request = strict_json(request_raw)
    require(isinstance(request, dict) and set(request) == {'schema','source','product','token','suite','args','deadlineMonotonic'}, 'wrong-request-fields')
    require(request['schema'] == 1 and type(request['schema']) is int and request['source'] == source and
        request['product'] == product and request['args'] == ARGS and valid_uuid(request['token']) and
        isinstance(request['suite'], str) and request['suite'].startswith('TouchColor.mac-ui.') and
        valid_uuid(request['suite'][len('TouchColor.mac-ui.'):]) and
        request['suite'][len('TouchColor.mac-ui.'):] != request['token'] and number(request['deadlineMonotonic']), 'wrong-request')
    fields = {'schema','route','source','requestSHA256','status','started','controllerStartedMonotonic',
        'deadlineMonotonic','launchRequests','terminateRequests','preexistingCount','caller','identity','callback',
        'terminated','cleanupConfirmed','reason','finished','finishedMonotonic','requested','requestedMonotonic',
        'callbackDeadlineMonotonic','callbackMonotonic','observationDeadlineMonotonic',
        'terminationRequested','terminationRequestedMonotonic','terminationDeadlineMonotonic','terminatedMonotonic'}
    require(isinstance(value, dict) and set(value) == fields, 'missing-or-unknown-control-fields')
    require(value['schema'] == 1 and type(value['schema']) is int and value['route'] == 'NSWorkspace' and
        value['source'] == source and value['requestSHA256'] == digest(request_raw), 'unbound-control')
    require(value['status'] == 'completed' and value['cleanupConfirmed'] is True and
        value['reason'] == 'process-launch-only-not-window-readiness', 'unknown-control-completion')
    require(type(value['launchRequests']) is int and value['launchRequests'] == 1 and
        type(value['terminateRequests']) is int and value['terminateRequests'] == 1 and
        type(value['preexistingCount']) is int and value['preexistingCount'] == 0, 'wrong-operation-count')
    validate_caller(value['caller'], controller_hash)
    identity = value['identity']
    require(isinstance(identity, dict) and set(identity) == {'product','pid','token','suite','args'} and
        identity['product'] == {**product, 'bundle': 'com.mango.touchColor'} and integer(identity['pid'], 1) and
        all(identity[k] == request[k] for k in ('token','suite','args')), 'wrong-callback-identity')
    times = ('started','requested','callback','terminationRequested','terminated','finished')
    require(all(number(value[k]) for k in times) and all(value[a] <= value[b] for a,b in zip(times,times[1:])), 'invalid-control-epochs')
    times = ('controllerStartedMonotonic','requestedMonotonic','callbackMonotonic',
        'terminationRequestedMonotonic','terminatedMonotonic','finishedMonotonic')
    require(all(number(value[k]) for k in times) and all(value[a] <= value[b] for a,b in zip(times,times[1:])), 'invalid-control-clock')
    start = value['controllerStartedMonotonic']; end = value['deadlineMonotonic']
    require(end == request['deadlineMonotonic'] and start < end <= start + CONTROL and value['finishedMonotonic'] < end, 'late-control')
    require(number(value['callbackDeadlineMonotonic']) and value['callbackMonotonic'] < value['callbackDeadlineMonotonic'] <= min(start + 60, end - 32), 'late-callback')
    require(0 < value['observationDeadlineMonotonic'] - value['callbackMonotonic'] <= 12.001 and
        value['terminationRequestedMonotonic'] < value['observationDeadlineMonotonic'] and
        number(value['terminationDeadlineMonotonic']) and value['terminatedMonotonic'] < value['terminationDeadlineMonotonic'] <= min(value['terminationRequestedMonotonic'] + 20, end), 'late-termination')
    # This minimal adapter is created ONLY after independently validating the
    # closed NSWorkspace receipt. It contains no fabricated XCTest case/test.
    return {'route': 'NSWorkspace', 'source': source, 'receipt_sha256': digest(raw),
        **product, 'pid': identity['pid'], 'token': identity['token'], 'args': ARGS,
        'started': value['requested'], 'result_end': value['finished']}


def observation(row):
    events = row['events']
    censuses = [e for e in events if not e['late'] and e.get('app', {}).get('present')]
    visible = any(any(w['visible'] and w['workspace'] for w in e['app']['windows']) for e in censuses)
    samples = [e for e in censuses if e['event'] == 'census']
    zero = [e for e in samples if e['app']['count'] == 0]
    # A late final has no census. Only classify the TWO actual timely samples,
    # never infer a whole-interval absence or reconstruct a missing sample.
    first = any(1 <= e['elapsed'] < 5 for e in zero)
    second = any(5 <= e['elapsed'] <= 10 for e in zero)
    last = max((e['sequence'] for e in samples), default=0)
    prefix_complete = (row['app_header_observed'] and not any(g <= last for g in row['sequence_gaps']) and
        not any(e['omittedRecords'] for e in events if e['sequence'] <= last))
    if visible: return 'visible-workspace-observed'
    if prefix_complete and first and second and len(samples) == len(zero):
        return 'zero-windows-at-retained-censuses'
    return 'unknown'


class Coordinator:
    """Fixed phases, one durable stop fence, immutable admission deadlines."""
    def __init__(self, budget, source, *, runner=capture, clock=time.monotonic, wall=time.time):
        self.budget, self.source, self.runner, self.clock, self.wall = budget, source, runner, clock, wall
        self.stopped = False
        self.durable_state = False
        self.value = {'schema': 1, 'source': source, 'phase': 'preparation', 'status': 'incomplete',
            'reason': 'not-started', 'commands': [], 'product': None, 'contact': None, 'control': None,
            'sourceFiles': {}, 'caller': None, 'confounders': CONFOUNDERS, 'acceptance': False}
        self.preparation_deadline = min(clock() + PREPARATION, clock() + budget.remaining('work'))
        self.value['preparationDeadlineMonotonic'] = self.preparation_deadline
        self.value['workDeadlineMonotonic'] = clock() + budget.remaining('work')
        self.value['budget'] = {'platform': PLATFORM, 'minutes': 25, 'workSeconds': 1020,
            'phaseCeilings': [500, 320, 80, 112], 'maximumTotal': 1012, 'overheadAtMaxima': 8,
            'startupMargin': STARTUP_MARGIN, 'reserves': RESERVES}

    def persist(self):
        self.durable_state = False
        self.value['admissions'] = list(self.budget.events)
        durable(STATE, self.value)
        self.durable_state = True

    def stop(self, reason):
        self.stopped = True
        self.durable_state = False
        self.value.update(status='incomplete', reason=reason)
        # No cleanup discovery, no new command, no evidence query after this.
        durable(LATCH, {'schema': 1, 'source': self.source, 'reason': reason, 'phase': self.value['phase']})
        self.persist()

    def invoke(self, label, argv, seconds, *, minimum=None, deadline=None, phase='work', cap=512*1024, cleanup=20):
        require(not self.stopped and not LATCH.exists(), 'uncertainty-fence')
        minimum = seconds if minimum is None else minimum
        granted = self.budget.admit(label, seconds, minimum=minimum, cleanup=cleanup, phase=phase)
        began = self.clock()
        absolute = min(began + granted, began + self.budget.remaining(phase) - cleanup,
            deadline - cleanup if deadline is not None else float('inf'))
        require(absolute - began >= minimum, 'insufficient-fixed-phase-admission')
        row = {'label': label, 'phase': self.value['phase'], 'argv': argv, 'startedMonotonic': began, 'startedEpoch': self.wall(),
            'deadlineMonotonic': absolute, 'cleanupDeadlineMonotonic': absolute + cleanup,
            'requestedSeconds': seconds, 'minimumSeconds': minimum, 'cleanupReserveSeconds': cleanup,
            'phaseCeilingMonotonic': deadline, 'captureCap': cap,
            'returned': False, 'exit': None, 'cleanupConfirmed': None, 'timely': False,
            'stdoutBytes': None, 'stderrBytes': None, 'stdoutSHA256': None, 'stderrSHA256': None}
        self.value['commands'].append(row); self.persist()
        # Persistence may consume time; never recreate a relative deadline.
        remaining = min(absolute - self.clock(), self.budget.remaining(phase) - cleanup)
        if remaining <= 0:
            self.stop('deadline-expired-before-spawn'); raise BudgetExhausted('deadline-expired-before-spawn')
        try:
            result = self.runner(argv, seconds=remaining, cap=cap, cleanup_grace=10 if cleanup==20 else 2)
            ended = self.clock()
            row.update(returned=True, exit=result.returncode, cleanupConfirmed=True,
                timely=ended < absolute, finishedMonotonic=ended, finishedEpoch=self.wall(),
                stdoutBytes=len(result.stdout), stderrBytes=len(result.stderr),
                stdoutSHA256=digest(result.stdout), stderrSHA256=digest(result.stderr))
            require(ended < absolute and ended < row['cleanupDeadlineMonotonic'] and
                (deadline is None or ended < deadline) and len(result.stdout)+len(result.stderr)<=cap,
                'late-or-oversized-command')
            self.persist()
            require(self.clock() < absolute and (deadline is None or self.clock() < deadline), 'late-command-persistence')
            return result
        except BaseException as error:
            if not row['returned']: row['cleanupConfirmed'] = getattr(error, 'cleanup_confirmed', None)
            self.stop('command-uncertain-' + type(error).__name__)
            raise

    def successful(self, *args, **kwargs):
        result = self.invoke(*args, **kwargs)
        require(result.returncode == 0, 'command-failed')
        return result.stdout

    def prepare(self):
        deadline = self.preparation_deadline
        def run(label, argv, seconds=20):
            return self.successful(label, argv, seconds, minimum=1, deadline=deadline)
        require(run('source-head', ['git','rev-parse','HEAD']).decode().strip() == self.source['sha'], 'wrong-checkout')
        require(run('source-clean', ['git','status','--porcelain','--untracked-files=all']) == b'', 'dirty-checkout')
        require(run('system-build', ['sw_vers','-buildVersion']).decode().strip() == '26A428', 'wrong-macos')
        require(run('architecture', ['uname','-m']).decode().strip() == 'arm64', 'wrong-architecture')
        version = run('toolchain', ['xcodebuild','-version']).decode().strip()
        require(version == 'Xcode 27.0\nBuild version 27A266a', 'wrong-xcode')
        self.value['toolchain'] = {'xcode': version, 'macOS': '27.0', 'build': '26A428', 'architecture': 'arm64'}
        self.value['sourceFiles'] = {p: digest(read_file(Path(p), 1_000_000)) for p in SOURCES}
        # Generate nothing and use the exact committed normal project once.
        run('build-for-testing', base_command() + ['build-for-testing'], 420)
        self.value['product'] = product_identity()
        run('compile-controller', ['xcrun','swiftc','-swift-version','5','-framework','AppKit','-framework','Security',
            'scripts/MacLaunchComparison.swift','-o',str(CONTROLLER)], 60)
        self.value['controllerSHA256'] = digest(read_file(CONTROLLER,16*1024*1024))
        caller_raw = run('inspect-caller', [str(CONTROLLER.absolute()),'inspect-caller'])
        self.value['caller'] = validate_caller(strict_json(caller_raw), self.value['controllerSHA256'])
        (ROOT/'caller.json').write_bytes(caller_raw)
        self.persist()
        require(self.clock() < deadline, 'preparation-exhausted')

    def contact(self):
        self.value['phase'] = 'xctest'
        result = self.invoke('single-contact-test', test_command(), TEST)
        require(result.returncode in (0,65), 'unknown-test-exit')
        self.value['contactCommandExit'] = result.returncode
        self.value['phase'] = 'intermediate-host-evidence'
        # This mandatory 80-second ceiling is charged to WORK, never borrowed
        # from the later contiguous 180-second evidence reserve.
        deadline = min(self.clock()+80, self.clock()+self.budget.remaining('work'))
        summary = self.successful('contact-summary', ['xcrun','xcresulttool','get','test-results','summary','--path',str(RESULT)],20,deadline=deadline)
        (ROOT/'mac-ui-summary.json').write_bytes(summary)
        self.successful('contact-attachments', ['xcrun','xcresulttool','export','attachments','--path',str(RESULT),
            '--output-path',str(ROOT/'screenshots')],20,deadline=deadline)
        self.value['contact'] = validate_contact(ROOT,self.value['product'],result.returncode)
        command=self.value['commands'][8]
        identity=self.value['contact']['identity']
        require(command['startedEpoch']<=identity['result_start']<=identity['result_end']<=command['finishedEpoch'], 'contact-outside-command')
        require(self.clock()<deadline, 'intermediate-evidence-late')
        self.persist()
        if self.clock()>=deadline:
            self.stop('intermediate-final-persistence-late')
            raise ValueError('intermediate-final-persistence-late')

    def control(self):
        self.value['phase'] = 'nsworkspace'
        require(product_identity() == self.value['product'], 'product-bytes-changed')
        # Full 112s is checked before creating the fixed absolute 92s request.
        self.budget.admit('ordinary-launch-controller',CONTROL,minimum=CONTROL,cleanup=CLEANUP)
        begin = self.clock(); deadline = min(begin+CONTROL,begin+self.budget.remaining('work')-CLEANUP)
        request = {'schema':1,'source':self.source,'product':self.value['product'],'args':ARGS,
            'token':str(uuid.uuid4()).upper(),'suite':'TouchColor.mac-ui.'+str(uuid.uuid4()).upper(),
            'deadlineMonotonic':deadline}
        require(request['token'] != self.value['contact']['identity']['token'], 'reused-route-token')
        request_raw = encode(request); (ROOT/'request.json').write_bytes(request_raw)
        self.persist()
        # Own full admission above; recheck after persistence without resetting it.
        require(self.clock()<deadline and self.budget.remaining('work') >= deadline-self.clock()+CLEANUP, 'control-admission-expired')
        result = self.invoke('ordinary-launch-controller', [str(CONTROLLER.absolute()),'launch-once',
            str((ROOT/'request.json').absolute()),str((ROOT/'control.json').absolute()),str(LATCH.absolute())],
            deadline-self.clock(), minimum=.001, deadline=deadline+CLEANUP)
        require(result.returncode==0 and not LATCH.exists(), 'control-unavailable')
        raw = read_file(ROOT/'control.json',16384)
        self.value['control'] = validate_control(raw,request_raw,self.source,self.value['product'],self.value['controllerSHA256'])
        require(self.clock()<deadline and product_identity()==self.value['product'], 'post-control-identity-or-time')
        self.value.update(status='routes-completed',reason='awaiting-passive-evidence'); self.persist()
        if self.clock()>=deadline:
            self.stop('control-final-persistence-late')
            raise ValueError('control-final-persistence-late')

    def run(self):
        try:
            self.prepare(); self.contact(); self.control()
        except BaseException as error:
            if not self.stopped: self.stop(str(error)[:160] if type(error) in (ValueError,BudgetExhausted) else 'stopped-' + type(error).__name__)
            if isinstance(error,(KeyboardInterrupt,SystemExit)): raise
        return self.value


def retain_files(value):
    """Local filesystem-only path, also safe after the uncertainty fence."""
    EVIDENCE.mkdir(parents=True,exist_ok=True)
    require(not EVIDENCE.is_symlink(), 'unsafe-evidence-root')
    files = {}; omissions = []
    candidates = [('state.json',STATE,128*1024),('request.json',ROOT/'request.json',16384),
        ('control.json',ROOT/'control.json',16384),('caller.json',ROOT/'caller.json',4096),('uncertain.json',LATCH,16384),
        ('mac-ui-summary.json',ROOT/'mac-ui-summary.json',512*1024)]
    if value.get('contact'):
        receipt = value['contact']['identity']['receipt_file']
        candidates += [(receipt,ROOT/receipt,4096),('screenshots/manifest.json',ROOT/'screenshots/manifest.json',512*1024)]
    for name,path,cap in candidates:
        if not path.exists(): omissions.append({'path':name,'reason':'unavailable'});continue
        raw = read_file(path,cap);target=EVIDENCE/name;target.parent.mkdir(parents=True,exist_ok=True)
        require(not target.parent.is_symlink() and not target.is_symlink(), 'unsafe-retention-path')
        target.write_bytes(raw);files[name]={'bytes':len(raw),'sha256':digest(raw)}
    # Unselected attachments remain runner-local; never silently imply pixels.
    manifest=ROOT/'screenshots/manifest.json'
    if manifest.exists():
        groups=strict_json(read_file(manifest,512*1024))
        for group in groups:
            for item in group.get('attachments',[]):
                name=item.get('exportedFileName','')
                if 'screenshots/'+name not in files:
                    omissions.append({'path':'screenshots/'+name,'reason':'outside-fixed-receipt-packet'})
    return files,omissions


def final_evidence(budget, source, runner=capture, clock=time.monotonic):
    began=clock();deadline=min(began+EVIDENCE_SECONDS,began+budget.remaining('evidence'))
    value=strict_json(read_file(STATE,128*1024));require(value['source']==source,'foreign-state')
    files,omissions=retain_files(value)
    report={'schema':1,'source':source,'acceptance':False,'status':'incomplete','contactOutcome':
        value['contact']['outcome'] if value.get('contact') else 'unknown','reason':value['reason'],
        'files':files,'omissions':omissions,'records':[],'observations':{},'confounders':CONFOUNDERS,
        'query':None,'evidenceStartedMonotonic':began,'evidenceDeadlineMonotonic':deadline}
    if not LATCH.exists() and value.get('control') and value.get('contact'):
        try:
            contact=validate_contact(EVIDENCE,value['product'],value['contactCommandExit'])
            control=validate_control(read_file(EVIDENCE/'control.json',16384),read_file(EVIDENCE/'request.json',16384),
                source,value['product'],value['controllerSHA256'])
            receipts=[contact['identity'],control]
            require(contact['identity']['token']!=control['token'] and contact['identity']['captured']<=control['started'], 'route-correlation')
            require(clock()+30<=deadline,'evidence-exhausted-before-query')
            query_start=clock();query_deadline=min(query_start+30,deadline)
            report['query']={'argv':passive.command(receipts),'startedMonotonic':query_start,
                'deadlineMonotonic':query_deadline,'returned':False,'cleanupConfirmed':None,'exit':None,
                'stdoutBytes':None,'stderrBytes':None,'stdoutSHA256':None,'stderrSHA256':None,'timely':False}
            durable(REPORT,report)
            require(clock()<query_deadline-4,'query-expired-before-spawn')
            result=runner(report['query']['argv'],seconds=query_deadline-4-clock(),cap=passive.RAW_LIMIT,cleanup_grace=2)
            q=report['query'];q.update(returned=True,cleanupConfirmed=True,exit=result.returncode,
                stdoutBytes=len(result.stdout),stderrBytes=len(result.stderr),stdoutSHA256=digest(result.stdout),
                stderrSHA256=digest(result.stderr),timely=clock()<query_deadline-4,finishedMonotonic=clock())
            require(q['timely'] and len(result.stdout)+len(result.stderr)<=passive.RAW_LIMIT,'late-query')
            # Raw scoped bytes are retained even if projection fails, never unrelated logs.
            for name,raw in [('lifecycle-query.json',result.stdout),('lifecycle-query-stderr.txt',result.stderr)]:
                (EVIDENCE/name).write_bytes(raw);files[name]={'bytes':len(raw),'sha256':digest(raw)}
            require(result.returncode==0 and passive.stderr_classification(result.stderr) in ('empty','unclassified'),'log-query-unavailable')
            rows=passive.project(result.stdout,receipts)
            require(clock()<query_deadline,'late-projection')
            report.update(status='observation-only',reason='route-comparison-with-order-and-restoration-confounders',records=rows,
                observations={'XCTest':observation(rows[0]),'NSWorkspace':observation(rows[1])})
        except BaseException as error:
            durable(LATCH,{'schema':1,'source':source,'phase':'evidence','reason':'evidence-uncertain-'+type(error).__name__})
            if isinstance(error,CaptureStopped) and report['query'] is not None:
                report['query']['cleanupConfirmed']=error.cleanup_confirmed
            report.update(status='incomplete',reason='passive-evidence-unavailable',records=[],observations={})
            if isinstance(error,(KeyboardInterrupt,SystemExit)): raise
    report['elapsedSeconds']=clock()-began
    require(clock()<deadline,'evidence-persistence-deadline')
    durable(REPORT,report,limit=256*1024)
    if clock()>=deadline:
        # No external operation follows a late final write. The workflow's
        # evidence-outcome gate also rejects any stale on-disk success record.
        durable(LATCH,{'schema':1,'source':source,'phase':'evidence','reason':'evidence-final-persistence-late'})
        report.update(status='incomplete',reason='evidence-final-persistence-late',records=[],observations={},elapsedSeconds=clock()-began)
        durable(REPORT,report,limit=256*1024)
        raise ValueError('evidence-final-persistence-late')
    return report


def validate_state(value, source):
    base={'schema','source','phase','status','reason','commands','product','contact','control','sourceFiles','caller',
        'confounders','acceptance','preparationDeadlineMonotonic','workDeadlineMonotonic','budget','admissions'}
    require(isinstance(value,dict) and base<=set(value)<=base|{'toolchain','controllerSHA256','contactCommandExit'}, 'unknown-state-fields')
    require(value['schema']==1 and type(value['schema']) is int and value['source']==source and value['acceptance'] is False and
        value['confounders']==CONFOUNDERS and value['status'] in ('incomplete','routes-completed'), 'invalid-state')
    require(value['budget']=={'platform':PLATFORM,'minutes':25,'workSeconds':1020,'phaseCeilings':[500,320,80,112],
        'maximumTotal':1012,'overheadAtMaxima':8,'startupMargin':STARTUP_MARGIN,'reserves':RESERVES}, 'budget-contract-changed')
    require(number(value['preparationDeadlineMonotonic']) and number(value['workDeadlineMonotonic']) and
        value['preparationDeadlineMonotonic']<=value['workDeadlineMonotonic'], 'invalid-state-deadlines')
    phases=['preparation']*8+['xctest']+['intermediate-host-evidence']*2+['nsworkspace']
    labels=['source-head','source-clean','system-build','architecture','toolchain','build-for-testing','compile-controller',
        'inspect-caller','single-contact-test','contact-summary','contact-attachments','ordinary-launch-controller']
    commands=value['commands'];require(isinstance(commands,list) and len(commands)<=12,'unbounded-command-plan')
    prior_end=None
    for index,row in enumerate(commands):
        fields={'label','phase','argv','startedMonotonic','startedEpoch','deadlineMonotonic','cleanupDeadlineMonotonic','requestedSeconds',
            'minimumSeconds','cleanupReserveSeconds','phaseCeilingMonotonic','captureCap','returned','exit','cleanupConfirmed',
            'timely','stdoutBytes','stderrBytes','stdoutSHA256','stderrSHA256'}
        require(isinstance(row,dict) and fields<=set(row)<=fields|{'finishedMonotonic','finishedEpoch'}, 'unknown-command-facts')
        require(row['label']==labels[index] and row['phase']==phases[index] and isinstance(row['argv'],list) and
            all(isinstance(x,str) and len(x)<2048 for x in row['argv']) and len(row['argv'])<=40, 'command-plan-mismatch')
        require(all(number(row[k]) for k in ('startedMonotonic','deadlineMonotonic','cleanupDeadlineMonotonic','requestedSeconds','minimumSeconds')) and
            0<row['minimumSeconds']<=row['requestedSeconds']<=420 and row['cleanupReserveSeconds']==20 and
            row['cleanupDeadlineMonotonic']==row['deadlineMonotonic']+20 and
            0<row['deadlineMonotonic']-row['startedMonotonic']<=row['requestedSeconds']+.000001 and
            row['cleanupDeadlineMonotonic']<=value['workDeadlineMonotonic']+.000001 and
            row['captureCap']==512*1024, 'command-deadline-mismatch')
        require(prior_end is None or prior_end<=row['startedMonotonic'],'nonsequential-commands')
        require(type(row['returned']) is bool and type(row['timely']) is bool and
            (row['cleanupConfirmed'] is None or type(row['cleanupConfirmed']) is bool), 'bad-command-state')
        if row['returned']:
            require(integer(row['exit'],-255) and row['cleanupConfirmed'] is True and
                number(row.get('finishedMonotonic')) and row['finishedMonotonic']>=row['startedMonotonic'] and
                number(row['startedEpoch']) and number(row.get('finishedEpoch')) and row['startedEpoch']<=row['finishedEpoch'] and
                all(integer(row[k]) for k in ('stdoutBytes','stderrBytes')) and
                all(sha(row[k]) for k in ('stdoutSHA256','stderrSHA256')),'incomplete-return-facts')
            prior_end=row['finishedMonotonic']
            require(row['timely']==(row['finishedMonotonic']<row['deadlineMonotonic']), 'timeliness-contradiction')
        else:
            require(all(row[k] is None for k in ('exit','stdoutBytes','stderrBytes','stdoutSHA256','stderrSHA256')) and
                row['timely'] is False,'invented-interrupted-output')
        if index<len(commands)-1 or value['status']=='routes-completed':
            require(row['returned'] and row['cleanupConfirmed'] is True and row['timely'] and
                row['exit'] in ((0,65) if index==8 else (0,)), 'continued-after-uncertainty')
        if index<8:
            require(row['phaseCeilingMonotonic']==value['preparationDeadlineMonotonic'] and
                row['cleanupDeadlineMonotonic']<=value['preparationDeadlineMonotonic'], 'preparation-ceiling-changed')
        if index==8:
            require(row['argv']==test_command() and row['requestedSeconds']==300 and row['minimumSeconds']==300,'wrong-single-test-admission')
        if index in (9,10): require(row['requestedSeconds']==20 and row['minimumSeconds']==20,'wrong-intermediate-cap')
        if index==11: require(row['requestedSeconds']<=92,'wrong-control-cap')
    require(value['phase'] in ('preparation','xctest','intermediate-host-evidence','nsworkspace') and
        isinstance(value['reason'],str) and len(value['reason'])<=160,'unknown-phase-state')
    if 'toolchain' in value:
        require(value['toolchain']=={'xcode':'Xcode 27.0\nBuild version 27A266a','macOS':'27.0','build':'26A428','architecture':'arm64'}, 'wrong-toolchain-state')
    require(value['sourceFiles']=={} or value['sourceFiles']=={p:digest(read_file(Path(p),1_000_000)) for p in SOURCES}, 'source-bytes-changed')
    require(isinstance(value['admissions'],list) and len(value['admissions'])<=16,'invalid-admissions')
    if value['status']=='routes-completed':
        require(len(commands)==12 and value['sourceFiles'] and value['contact'] and value['control'] and sha(value['controllerSHA256']), 'incomplete-route-state')
        validate_caller(value['caller'],value['controllerSHA256'])
        admissions=[e for e in value['admissions'] if e['label']=='ordinary-launch-controller']
        require(len(admissions)==2 and admissions[0]['requested_seconds']==92 and admissions[0]['minimum_seconds']==92 and
            admissions[0]['cleanup_reserve_seconds']==20 and admissions[0]['admitted'] is True,'missing-full-control-admission')
    return value


def validate_packet(root, source):
    report=strict_json(read_file(root/'mac-launch-comparison.json',256*1024))
    report_fields={'schema','source','acceptance','status','contactOutcome','reason','files','omissions','records','observations','confounders',
        'query','evidenceStartedMonotonic','evidenceDeadlineMonotonic','elapsedSeconds'}
    require(isinstance(report,dict) and set(report)==report_fields, 'unknown-report-fields')
    require(number(report['evidenceStartedMonotonic']) and number(report['evidenceDeadlineMonotonic']) and
        number(report['elapsedSeconds']) and 0<=report['elapsedSeconds']<report['evidenceDeadlineMonotonic']-report['evidenceStartedMonotonic']<=180, 'evidence-phase-deadline')
    require(report['source']==source and type(report['schema']) is int and report['schema']==1 and report['acceptance'] is False and report['confounders']==CONFOUNDERS,'unbound-report')
    require(report['status'] in ('incomplete','observation-only') and report['contactOutcome'] in ('unknown','failed','passed'), 'invalid-report-state')
    require(isinstance(report['files'],dict) and len(report['files'])<=12,'unbounded-packet-files')
    roots={'state.json','request.json','control.json','caller.json','uncertain.json','mac-ui-summary.json',
        'screenshots/manifest.json','lifecycle-query.json','lifecycle-query-stderr.txt'}
    for name,record in report['files'].items():
        require(isinstance(name,str) and (name in roots or re.fullmatch(r'screenshots/[0-9A-Fa-f-]{36}\.txt',name)) and
            isinstance(record,dict) and set(record)=={'bytes','sha256'} and integer(record['bytes']) and sha(record['sha256']), 'unapproved-packet-file')
    require(isinstance(report['omissions'],list) and len(report['omissions'])<=520,'unbounded-omissions')
    for row in report['omissions']:
        require(isinstance(row,dict) and set(row)=={'path','reason'} and isinstance(row['path'],str) and
            len(row['path'])<=160 and '..' not in Path(row['path']).parts and not Path(row['path']).is_absolute() and
            row['reason'] in ('unavailable','outside-fixed-receipt-packet'),'invalid-omission')
    allowed=set(report['files'])|{'mac-launch-comparison.json'}
    total=0
    for path in root.rglob('*'):
        require(not path.is_symlink(),'linked-packet')
        if path.is_dir(): continue
        name=path.relative_to(root).as_posix();require(name in allowed,'unlisted-packet-file')
        raw=read_file(path,LIMIT);total+=len(raw)
        if name in report['files']:require(report['files'][name]=={'bytes':len(raw),'sha256':digest(raw)},'changed-captured-bytes')
    require(total<=LIMIT and set(report['files'])=={p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}-{'mac-launch-comparison.json'},'packet-bound')
    state=validate_state(strict_json(read_file(root/'state.json',128*1024)),source)
    require(state['source']==source and state['confounders']==CONFOUNDERS and state['acceptance'] is False,'foreign-state')
    if report['status']=='observation-only':
        require('uncertain.json' not in report['files'] and state['status']=='routes-completed','projection-after-fence')
        contact=validate_contact(root,state['product'],state['contactCommandExit'])
        control=validate_control(read_file(root/'control.json',16384),read_file(root/'request.json',16384),source,state['product'],state['controllerSHA256'])
        require(state['commands'][8]['startedEpoch']<=contact['identity']['result_start']<=contact['identity']['result_end']<=state['commands'][8]['finishedEpoch'], 'contact-command-time-mismatch')
        receipt=strict_json(read_file(root/'control.json',16384));command=state['commands'][11]
        require(command['startedMonotonic']<=receipt['controllerStartedMonotonic']<receipt['finishedMonotonic']<=command['finishedMonotonic'] and
            receipt['deadlineMonotonic']==command['deadlineMonotonic'], 'control-command-time-mismatch')
        caller_raw=read_file(root/'caller.json',4096)
        require(strict_json(caller_raw)==state['caller'] and digest(caller_raw)==state['commands'][7]['stdoutSHA256'], 'caller-capture-mismatch')
        summary_raw=read_file(root/'mac-ui-summary.json',512*1024)
        require(digest(summary_raw)==state['commands'][9]['stdoutSHA256'], 'summary-capture-mismatch')
        require(contact['outcome']==report['contactOutcome'] and contact==state['contact'] and control==state['control'],'changed-route-receipts')
        raw=read_file(root/'lifecycle-query.json',passive.RAW_LIMIT)
        errors=read_file(root/'lifecycle-query-stderr.txt',passive.RAW_LIMIT)
        q=report['query']
        require(isinstance(q,dict) and set(q)=={'argv','startedMonotonic','deadlineMonotonic','returned','cleanupConfirmed','exit',
            'stdoutBytes','stderrBytes','stdoutSHA256','stderrSHA256','timely','finishedMonotonic'},'unknown-query-fields')
        require(q['argv']==passive.command([contact['identity'],control]) and q['returned'] is True and q['cleanupConfirmed'] is True and
            q['exit']==0 and q['timely'] is True and q['stdoutBytes']==len(raw) and q['stderrBytes']==len(errors) and
            q['stdoutSHA256']==digest(raw) and q['stderrSHA256']==digest(errors) and len(raw)+len(errors)<=passive.RAW_LIMIT and
            q['startedMonotonic']<q['finishedMonotonic']<q['deadlineMonotonic']-4 and
            q['deadlineMonotonic']-q['startedMonotonic']<=30 and passive.stderr_classification(errors) in ('empty','unclassified'),'unbound-query')
        rows=passive.project(raw,[contact['identity'],control])
        require(rows==report['records'] and report['observations']=={'XCTest':observation(rows[0]),'NSWorkspace':observation(rows[1])},'unbound-projection')
        require(len(encode(rows))<=passive.OUTPUT_LIMIT and report['elapsedSeconds']<EVIDENCE_SECONDS,'projection-bound')
    else: require(report['records']==[] and report['observations']=={},'incomplete-invented-observations')
    return report


def console(value, durable_state):
    # One nonblocking atomic <=512-byte line; failure to print is not a retry.
    row={'source':value.get('source',{}).get('sha'),'run':value.get('source',{}).get('run'),
        'attempt':value.get('source',{}).get('attempt'),'phase':value.get('phase','evidence'),
        'status':value.get('status','incomplete'),'durability':'file-and-directory-fsync' if durable_state else 'unconfirmed'}
    raw=b'MAC_LAUNCH_COMPARISON '+encode(row)
    if len(raw)>512:return
    try:
        descriptor=sys.stdout.fileno();os.set_blocking(descriptor,False);os.write(descriptor,raw)
    except (OSError,ValueError): pass


def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['run','evidence','validate','contact-result']);args=parser.parse_args()
    source=source_identity(os.environ);budget=load_budget()
    require(budget.record['platform']==PLATFORM and budget.record['minutes']==25,'wrong-budget')
    require(all(not parent.is_symlink() for parent in (ROOT,*ROOT.parents)),'unsafe-root')
    ROOT.mkdir(parents=True,exist_ok=True)
    if args.action=='contact-result':
        require(time.monotonic()<budget.hard_deadline,'outcome-guard-late')
        report=strict_json(read_file(REPORT,256*1024))
        require(report['source']==source and report['acceptance'] is False,'foreign-outcome')
        console(report,True)
        return 0 if report['contactOutcome']=='passed' else 1
    if args.action=='run':
        require(not STATE.exists() and not LATCH.exists(),'stale-run')
        coordinator=Coordinator(budget,source);result=coordinator.run();console(result,coordinator.durable_state)
        return 0 if result['status']=='routes-completed' else 1
    if args.action=='evidence':
        result=final_evidence(budget,source);console(result,True);return 0
    require(budget.remaining('validation')>=60,'validation-exhausted')
    deadline=min(time.monotonic()+60,time.monotonic()+budget.remaining('validation'))
    result=validate_packet(EVIDENCE,source)
    require(time.monotonic()<deadline,'validation-late')
    console(result,True);return 0


if __name__=='__main__': raise SystemExit(main())
