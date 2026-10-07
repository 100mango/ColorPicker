"""One fixed sandbox Chinese contact via Xcode test plan; no launch permutation."""
import argparse
import os
import plistlib
from pathlib import Path
import re
import sys
import time

from job_budget import load as load_budget, BudgetExhausted, RESERVES, STARTUP_MARGIN
from palette_lifecycle_diagnostics import capture, CaptureStopped
from retain_mac_evidence import strict_json, read_file
import mac_passive_lifecycle as passive
# Reuse only checked pure serialization; never the two-route executor.
from mac_launch_comparison import durable
from mac_chinese_contract import validate_chinese_contact as validate_contact, parse_runner_locale, app_language_observation

PLATFORM = 'mac-chinese-contact'
BRANCH = 'refs/heads/codex/mac-chinese-contact'
WORKFLOW = '.github/workflows/mac-chinese-contact.yml'
PARENT = 'ea9da854f4658b36a28a3b80f6f48e06185cfedb'
CASE = passive.CASES[1]
ROOT = Path('build/mac-chinese-contact')
STATE = ROOT / 'state.json'
LATCH = ROOT / 'uncertain.json'
EVIDENCE = Path('build/evidence')
REPORT = EVIDENCE / 'mac-chinese-contact.json'
VALIDATED = ROOT / 'validated-outcome.json'
VALIDATION_ATTEMPT = ROOT / 'validation-attempt.json'
RESULT = ROOT / 'contact.xcresult'
PREPARATION = 500
TEST = 300
EVIDENCE_SECONDS = 180
LIMIT = 3_000_000
SOURCES = (WORKFLOW, 'scripts/mac_chinese_contact.py', 'scripts/mac_launch_comparison.py',
    'scripts/mac_passive_lifecycle.py', 'scripts/mac_chinese_contract.py', 'scripts/MacRunnerLocale.swift', 'scripts/job_budget.py', 'scripts/atomic_json.py',
    'scripts/bounded_process.py', 'scripts/palette_lifecycle_diagnostics.py', 'scripts/retain_mac_evidence.py',
    'TouchColorMac/TouchColorMacApp.swift', 'TouchColorMac/ColorWindow.swift',
    'TouchColorMacUITests/TouchColorMacUITests.swift', 'TouchColorMac.xcodeproj/project.pbxproj',
    'TouchColorMac.xcodeproj/xcshareddata/xcschemes/TouchColorMac.xcscheme',
    'TouchColorMac/en.lproj/Localizable.strings', 'TouchColorMac/zh-Hans.lproj/Localizable.strings',
    'TouchColorMac/TouchColorMac.entitlements', 'TouchColorMacChineseContact.xctestplan',
    'TouchColorMac.xcodeproj/xcshareddata/xcschemes/TouchColorMacSandboxChineseContact.xcscheme')
INTERPRETATION = 'one-Chinese-sandbox-contact-result-not-full-Mac-release-acceptance'
MINIMAL_ENTITLEMENTS = {'com.apple.security.app-sandbox':True,'com.apple.security.files.user-selected.read-write':True,
    'com.apple.security.device.camera':True,'com.apple.security.get-task-allow':True}
LOCALIZATION = {'language':'zh-Hans','region':'CN','configuration':'Chinese','mechanism':'Xcode-test-plan'}
APP = Path('build/mac-sandbox/Build/Products/Debug/TouchColor.app')
ENTITLEMENTS = ROOT/'minimal.entitlements'
TEST_INDEX=10
SUMMARY_INDEX=13
EXPORT_INDEX=14
TOOLCHAIN = {'xcode': 'Xcode 27.0\nBuild version 27A266a', 'macOS': '27.0', 'build': '26A428', 'architecture': 'arm64'}
BUDGET = {'platform': PLATFORM, 'minutes': 25, 'workSeconds': 1020, 'preparationSeconds': 500,
    'testCommandSeconds': 300, 'testCleanupSeconds': 20, 'maximumWorkPhases': 820, 'workHeadroom': 200,
    'runnerLocaleProbeWithCleanup': 40, 'sandboxPreparationCommandsWithCleanup':120, 'sandboxPostflightInsideTestAllocation':80, 'evidenceSeconds': 180, 'summaryWithCleanup': 40, 'attachmentsWithCleanup': 40,
    'queryWithCleanup': 0, 'evidenceLocalHeadroom': 100, 'startupMargin': STARTUP_MARGIN, 'reserves': RESERVES}


def require(ok, reason):
    if not ok: raise ValueError(reason)
def digest(raw): return passive.digest(raw)
def encode(value): return passive.encode(value)
def number(value): return passive.number(value)
def integer(value, low=0): return type(value) is int and value >= low
def sha(value): return isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None


def source_identity(env):
    fixed = {'GITHUB_REPOSITORY': '100mango/ColorPicker', 'GITHUB_REF': BRANCH, 'GITHUB_EVENT_NAME': 'push',
        'GITHUB_WORKFLOW_REF': '100mango/ColorPicker/' + WORKFLOW + '@' + BRANCH,
        'TOUCHCOLOR_JOB_PLATFORM': PLATFORM, 'TOUCHCOLOR_JOB_LANE': PLATFORM,
        'TOUCHCOLOR_JOB_MINUTES': '25', 'TOUCHCOLOR_EVIDENCE_LIMIT': str(LIMIT)}
    require(all(env.get(k) == v for k, v in fixed.items()), 'wrong-fixed-workflow')
    require(re.fullmatch('[0-9a-f]{40}', env.get('GITHUB_SHA', '')) is not None and
        env.get('GITHUB_WORKFLOW_SHA') == env['GITHUB_SHA'], 'wrong-source')
    require(all(re.fullmatch('[1-9][0-9]{0,19}', env.get(k, '')) for k in ('GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT')), 'wrong-run')
    return dict(repository=fixed['GITHUB_REPOSITORY'], ref=BRANCH, workflow=WORKFLOW,
        workflow_ref=fixed['GITHUB_WORKFLOW_REF'], event='push', sha=env['GITHUB_SHA'],
        run=env['GITHUB_RUN_ID'], attempt=env['GITHUB_RUN_ATTEMPT'], parent=PARENT, route='Chinese-sandbox-test-plan')


def base_command():
    # The original ad-hoc sandbox build settings; no account or new permission.
    return ['xcodebuild','-quiet','-project','TouchColorMac.xcodeproj','-scheme','TouchColorMacSandboxChineseContact',
        '-testPlan','TouchColorMacChineseContact','-configuration','Debug','-destination','platform=macOS,arch=arm64',
        '-derivedDataPath','build/mac-sandbox','ARCHS=arm64','CODE_SIGNING_ALLOWED=YES','CODE_SIGN_STYLE=Manual',
        'CODE_SIGN_IDENTITY=-','DEVELOPMENT_TEAM=','TOUCHCOLOR_ENABLE_SANDBOX=YES',
        'TOUCHCOLOR_SANDBOX_ENTITLEMENTS=TouchColorMac/TouchColorMac.entitlements']


def product_identity():
    app=APP.absolute()
    require(app.resolve()==app and app.is_dir() and not app.is_symlink(),'unsafe-sandbox-product-path')
    metadata=plistlib.loads(read_file(app/'Contents/Info.plist',128*1024))
    require(metadata.get('CFBundleIdentifier')=='com.mango.touchColor' and metadata.get('CFBundleExecutable')=='TouchColor','wrong-sandbox-product')
    executable=app/'Contents/MacOS/TouchColor';logic=app/'Contents/MacOS/TouchColor.debug.dylib'
    require(executable.resolve()==executable and logic.resolve()==logic,'linked-sandbox-product')
    return dict(applicationPath=str(app),executable=str(executable),executableSHA256=digest(read_file(executable,16*1024*1024)),
        logicSHA256=digest(read_file(logic,16*1024*1024)))


def parse_entitlements(raw):
    require(len(raw)<=4096,'entitlements-byte-cap')
    value=plistlib.loads(raw)
    require(isinstance(value,dict) and set(value)==set(MINIMAL_ENTITLEMENTS) and
        all(value[k] is True for k in MINIMAL_ENTITLEMENTS),'unexpected-sandbox-entitlements')
    return value


def prepare_entitlements():
    value=plistlib.loads(read_file(Path('TouchColorMac/TouchColorMac.entitlements'),4096))
    require(value=={k:v for k,v in MINIMAL_ENTITLEMENTS.items() if k!='com.apple.security.get-task-allow'} and
        all(v is True for v in value.values()),'changed-shipping-entitlement-source')
    require(not ENTITLEMENTS.exists() and not ENTITLEMENTS.is_symlink(),'preexisting-signing-input')
    ENTITLEMENTS.write_bytes(plistlib.dumps(MINIMAL_ENTITLEMENTS))
    parse_entitlements(read_file(ENTITLEMENTS,4096))


def test_command():
    return base_command()+['-resultBundlePath',str(RESULT),'-parallel-testing-enabled','NO',
        '-collect-test-diagnostics','never','-test-timeouts-enabled','YES','-maximum-test-execution-time-allowance','120',
        '-only-testing:TouchColorMacUITests/TouchColorMacUITests/'+CASE,'test-without-building']


def plan(contact=None):
    # One original Chinese case; no boundary probe, whole suite, or lifecycle query.
    return [
        ('source-head',['git','show','--no-patch','--format=%H%n%P','HEAD'],20,1,20,'preparation'),
        ('source-clean',['git','status','--porcelain','--untracked-files=all'],20,1,20,'preparation'),
        ('system-build',['sw_vers','-buildVersion'],20,1,20,'preparation'),
        ('architecture',['uname','-m'],20,1,20,'preparation'),
        ('toolchain',['xcodebuild','-version'],20,1,20,'preparation'),
        ('runner-locale',['xcrun','swift','-swift-version','5','scripts/MacRunnerLocale.swift'],20,20,20,'preparation'),
        ('build-for-testing',base_command()+['build-for-testing'],420,1,20,'preparation'),
        ('minimal-ad-hoc-sign',['codesign','--force','--sign','-','--entitlements',str(ENTITLEMENTS),str(APP)],20,20,20,'preparation'),
        ('verify-sandbox-signature',['codesign','--verify','--deep','--strict','--verbose=2',str(APP)],20,20,20,'preparation'),
        ('read-sandbox-entitlements',['codesign','-d','--entitlements',':-',str(APP)],20,20,20,'preparation'),
        ('single-Chinese-contact',test_command(),300,300,20,'xctest'),
        ('post-verify-sandbox-signature',['codesign','--verify','--deep','--strict','--verbose=2',str(APP)],20,20,20,'xctest'),
        ('post-read-sandbox-entitlements',['codesign','-d','--entitlements',':-',str(APP)],20,20,20,'xctest'),
        ('contact-summary',['xcrun','xcresulttool','get','test-results','summary','--path',str(RESULT)],20,20,20,'evidence'),
        ('contact-attachments',['xcrun','xcresulttool','export','attachments','--path',str(RESULT),'--output-path',str(ROOT/'screenshots')],20,20,20,'evidence')]


class Diagnostic:
    def __init__(self, budget, source, *, runner=capture, clock=time.monotonic, wall=time.time, state=None):
        self.budget, self.source, self.runner, self.clock, self.wall = budget, source, runner, clock, wall
        self.stopped = False; self.durable_state = False
        if state is not None:
            self.value = state
            self.budget.events = list(state['admissions'])
            return
        began = clock(); work = min(began + budget.remaining('work'), budget.record['started_monotonic'] + 1020)
        self.value = dict(schema=1, source=source, phase='preparation', status='incomplete', reason='not-started',
            acceptance=False, interpretation=INTERPRETATION, commands=[], product=None, contact=None,
            sourceFiles={}, toolchain=None, runnerLocale=None, sandboxBefore=None, sandboxAfter=None, admissions=[], budget=BUDGET, jobClock=budget.record,
            createdMonotonic=began, workDeadlineMonotonic=work,
            preparationDeadlineMonotonic=min(began + PREPARATION, work))

    def persist(self):
        self.durable_state = False
        self.value['admissions'] = list(self.budget.events)
        durable(STATE, self.value)
        self.durable_state = True

    def fence(self, reason):
        self.stopped = True; self.durable_state = False
        self.value.update(status='incomplete', reason=str(reason)[:160])
        try:
            durable(LATCH, dict(schema=1, source=self.source, phase=self.value['phase'], reason=self.value['reason']))
            self.persist()
        except BaseException:
            # No stale complete state may survive an unconfirmed failure write.
            try: STATE.unlink(missing_ok=True)
            except OSError: pass
            raise

    def invoke_next(self):
        require(not self.stopped and not LATCH.exists(), 'uncertainty-fence')
        index = len(self.value['commands']); commands = plan(self.value['contact'])
        require(index < len(commands), 'no-further-command')
        label, argv, seconds, minimum, cleanup, phase = commands[index]
        self.value['phase'] = phase
        ceiling = (self.value['preparationDeadlineMonotonic'] if phase == 'preparation' else
            (self.value['commands'][TEST_INDEX]['deadlineMonotonic'] if index>TEST_INDEX else self.value['workDeadlineMonotonic']) if phase == 'xctest' else self.value['evidenceDeadlineMonotonic'])
        budget_phase = 'evidence' if phase == 'evidence' else 'work'
        granted = self.budget.admit(label, seconds, minimum=minimum, cleanup=cleanup, phase=budget_phase)
        began = self.clock()
        deadline = min(began + granted, ceiling - cleanup, began + self.budget.remaining(budget_phase) - cleanup)
        require(deadline >= began + minimum, 'insufficient-full-phase-admission')
        row = dict(label=label, phase=phase, argv=argv, requestedSeconds=seconds, minimumSeconds=minimum,
            cleanupReserveSeconds=cleanup, captureCap=4096 if label=='runner-locale' else 512*1024, startedMonotonic=began, startedEpoch=self.wall(),
            deadlineMonotonic=deadline, cleanupDeadlineMonotonic=deadline + cleanup, phaseCeilingMonotonic=ceiling,
            returned=False, exit=None, cleanupConfirmed=None, timely=False, stdoutBytes=None, stderrBytes=None,
            stdoutSHA256=None, stderrSHA256=None)
        self.value['commands'].append(row)
        try:
            self.persist()  # Durable attempt precedes any spawn; never retried.
            remaining = min(deadline - self.clock(), self.budget.remaining(budget_phase) - cleanup)
            require(remaining > 0 and self.clock() < ceiling - cleanup, 'deadline-before-spawn')
            result = self.runner(argv, seconds=remaining, cap=row['captureCap'], cleanup_grace=2 if cleanup == 4 else 10)
            ended = self.clock()
            row.update(returned=True, exit=result.returncode, cleanupConfirmed=True, timely=ended < deadline,
                finishedMonotonic=ended, finishedEpoch=self.wall(), stdoutBytes=len(result.stdout),
                stderrBytes=len(result.stderr), stdoutSHA256=digest(result.stdout), stderrSHA256=digest(result.stderr))
            require(ended < deadline and len(result.stdout) + len(result.stderr) <= row['captureCap'], 'late-or-oversized-command')
            require(result.returncode in ((0,65) if index == TEST_INDEX else (0,)), 'unexpected-command-exit')
            self.persist()
            require(self.clock() < deadline and self.clock() < ceiling, 'late-command-persistence')
            return result
        except BaseException as error:
            if not row['returned']:
                row['cleanupConfirmed'] = getattr(error, 'cleanup_confirmed', None)
                if row['cleanupConfirmed'] is True:
                    row.update(finishedMonotonic=self.clock(), finishedEpoch=self.wall())
            self.fence('command-uncertain-' + type(error).__name__)
            raise

    def run(self):
        try:
            self.persist()
            require(self.invoke_next().stdout.decode().strip().splitlines() == [self.source['sha'], PARENT], 'wrong-sole-parent-source')
            require(self.invoke_next().stdout == b'', 'dirty-checkout')
            require(self.invoke_next().stdout.decode().strip() == TOOLCHAIN['build'], 'wrong-macos')
            require(self.invoke_next().stdout.decode().strip() == TOOLCHAIN['architecture'], 'wrong-architecture')
            require(self.invoke_next().stdout.decode().strip() == TOOLCHAIN['xcode'], 'wrong-xcode')
            self.value['toolchain'] = dict(TOOLCHAIN)
            locale_raw=self.invoke_next().stdout
            self.value['runnerLocale']=parse_runner_locale(locale_raw)
            (ROOT/'runner-locale.json').write_bytes(locale_raw)
            require(self.clock()<self.value['preparationDeadlineMonotonic'],'runner-locale-observation-late')
            self.value['sourceFiles'] = {p: digest(read_file(Path(p), 1_000_000)) for p in SOURCES}
            require(self.clock() < self.value['preparationDeadlineMonotonic'], 'late-source-hashing')
            prepare_entitlements()
            require(self.clock()<self.value['preparationDeadlineMonotonic'],'signing-input-preparation-late')
            self.invoke_next()  # One sandbox build.
            self.invoke_next()  # Original disposable ad-hoc re-sign, exact four keys.
            self.invoke_next()  # Original strict signature verification.
            raw=self.invoke_next().stdout
            self.value['sandboxBefore']=parse_entitlements(raw)
            (ROOT/'sandbox-before.plist').write_bytes(raw)
            self.value['product']=product_identity()
            self.persist()
            require(self.clock()<self.value['preparationDeadlineMonotonic'],'late-sandbox-preparation')
            self.invoke_next()  # Exactly the original Chinese contact once.
            self.invoke_next()  # Postchecks use only remaining original test work time, never its cleanup reserve.
            raw=self.invoke_next().stdout
            self.value['sandboxAfter']=parse_entitlements(raw)
            require(self.value['sandboxAfter']==self.value['sandboxBefore'],'runtime-entitlements-changed')
            (ROOT/'sandbox-after.plist').write_bytes(raw)
            require(product_identity()==self.value['product'],'runtime-product-bytes-changed')
            self.value.update(status='test-closed',reason='awaiting-exact-Chinese-contact-result')
            self.persist()
            require(self.clock()<self.value['commands'][-1]['deadlineMonotonic'] and
                self.clock()<self.value['commands'][TEST_INDEX]['deadlineMonotonic'],'late-final-test-persistence')
        except BaseException as error:
            if not self.stopped: self.fence(str(error)[:160] if isinstance(error,(ValueError,BudgetExhausted)) else type(error).__name__)
            if isinstance(error, (KeyboardInterrupt,SystemExit)): raise
        return self.value


def admit_summary(raw, test):
    """Reject impossible one-case summaries before exporting any attachments.

    This is only admission; the original complete receipt/product validator
    still runs after export. No identity or acceptance is inferred here.
    """
    summary=strict_json(raw)
    require(isinstance(summary,dict),'bad-pre-export-summary')
    counts=('passedTests','failedTests','skippedTests','expectedFailures','totalTestCount')
    require(all(integer(summary.get(key)) for key in counts),'invalid-pre-export-counts')
    require(summary['totalTestCount']==1 and summary['skippedTests']==0 and summary['expectedFailures']==0 and
        summary['passedTests']+summary['failedTests']==1,'not-exact-pre-export-case')
    passed=summary['passedTests']==1
    require(summary.get('result')==('Passed' if passed else 'Failed') and test['exit']==(0 if passed else 65),
        'pre-export-outcome-mismatch')
    start,end=summary.get('startTime'),summary.get('finishTime')
    require(number(start) and number(end) and test['startedEpoch']<=start<end<=test['finishedEpoch'],
        'pre-export-summary-outside-test-clock')


def closed_contact(value, root):
    require(len(value['commands']) >= 15 and value['product'] is not None, 'missing-contact-command-prefix')
    test, summary = value['commands'][TEST_INDEX], value['commands'][SUMMARY_INDEX]
    require(all(c['returned'] and c['timely'] and c['cleanupConfirmed'] is True for c in value['commands'][:15]), 'unclosed-prefix')
    contact = validate_contact(root, value['product'], test['exit'])
    identity = contact['identity']
    require(test['startedEpoch'] <= identity['result_start'] <= identity['result_end'] <= test['finishedEpoch'], 'case-outside-test-command')
    require(contact['summarySHA256'] == summary['stdoutSHA256'], 'summary-not-captured-by-command')
    return contact


def retain(value):
    """Only bounded own-source files; other XCTest attachments stay runner-local."""
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    require(not EVIDENCE.is_symlink(), 'unsafe-evidence-root')
    candidates = [('state.json', read_file(STATE,128*1024))]
    if value['runnerLocale'] is not None:candidates.append(('runner-locale.json',read_file(ROOT/'runner-locale.json',4096)))
    for field,name in [('sandboxBefore','sandbox-before.plist'),('sandboxAfter','sandbox-after.plist')]:
        if value[field] is not None:candidates.append((name,read_file(ROOT/name,4096)))
    if LATCH.exists(): candidates.append(('uncertain.json', read_file(LATCH,16384)))
    if value['contact'] is not None:
        names = [('mac-ui-summary.json',512*1024), ('screenshots/manifest.json',512*1024),
            (value['contact']['identity']['receipt_file'],4096)]
        candidates.extend((name, read_file(ROOT/name,cap)) for name,cap in names)
    require(sum(len(raw) for _,raw in candidates) + 256*1024 <= LIMIT, 'packet-cap')
    files = {}
    for name, raw in candidates:
        target = EVIDENCE/name; target.parent.mkdir(parents=True, exist_ok=True)
        require(not target.is_symlink() and not target.parent.is_symlink(), 'unsafe-retention-path')
        target.write_bytes(raw); files[name] = dict(bytes=len(raw), sha256=digest(raw))
    return files


def evidence(budget, source, *, runner=capture, clock=time.monotonic, wall=time.time):
    began=clock(); deadline=min(began+180,began+budget.remaining('evidence'))
    require(deadline > began, 'no-evidence-time')
    require(not REPORT.exists(), 'evidence-already-attempted')
    value = validate_state(strict_json(read_file(STATE,128*1024)), source)
    require(clock()<deadline,'evidence-state-validation-late')
    require('evidenceDeadlineMonotonic' not in value, 'evidence-already-started')
    diagnostic = Diagnostic(budget,source,runner=runner,clock=clock,wall=wall,state=value)
    value.update(evidenceStartedMonotonic=began,evidenceDeadlineMonotonic=deadline)
    report=dict(schema=1,source=source,acceptance=False,interpretation=INTERPRETATION,status='incomplete',
        reason=value['reason'],contactOutcome='unknown',files={},otherAttachments='not-retained',
        route='Chinese-sandbox-test-plan',requestedLocalization=LOCALIZATION,singleChineseSandboxContactQualification=False,
        runnerLocale=value['runnerLocale'],appLanguageObservation=app_language_observation({},None),
        evidenceStartedMonotonic=began,evidenceDeadlineMonotonic=deadline)
    try:
        EVIDENCE.mkdir(parents=True,exist_ok=True)
        require(all(not p.is_symlink() for p in (EVIDENCE,*EVIDENCE.parents)),'unsafe-evidence-root')
        diagnostic.persist()
        durable(REPORT,report,limit=256*1024)  # One persisted attempt, before any evidence command.
        require(clock() < deadline, 'evidence-start-persistence-late')
        if value['status']=='test-closed' and not LATCH.exists():
            summary=diagnostic.invoke_next().stdout
            admit_summary(summary,value['commands'][TEST_INDEX])
            (ROOT/'mac-ui-summary.json').write_bytes(summary)
            require(clock()<deadline,'summary-write-late')
            diagnostic.invoke_next()
            value['contact']=closed_contact(value,ROOT)
            diagnostic.persist()
            require(clock()<deadline,'contact-validation-late')
            report.update(status='contact-observed',reason='original-Chinese-contact-result')
            value.update(status='evidence-completed',reason='original-Chinese-contact-result')
            diagnostic.persist()
            require(clock()<deadline,'evidence-state-persistence-late')
        report['contactOutcome']=value['contact']['outcome'] if value['contact'] else 'unknown'
        report['appLanguageObservation']=app_language_observation(strict_json(read_file(ROOT/'mac-ui-summary.json',512*1024)),value['contact']) if value['contact'] else app_language_observation({},None)
    except BaseException as error:
        if not diagnostic.stopped: diagnostic.fence('evidence-uncertain-'+type(error).__name__)
        report.update(status='incomplete',reason=value['reason'],
            contactOutcome=value['contact']['outcome'] if value['contact'] else 'unknown')
        report['appLanguageObservation']=app_language_observation(strict_json(read_file(ROOT/'mac-ui-summary.json',512*1024)),value['contact']) if value['contact'] else app_language_observation({},None)
        if isinstance(error,(KeyboardInterrupt,SystemExit)): raise
    try:
        report['singleChineseSandboxContactQualification']=report['status']=='contact-observed' and report['contactOutcome']=='passed'
        report['files']=retain(value)
        report['elapsedSeconds']=clock()-began
        require(clock()<deadline,'retention-late')
        durable(REPORT,report,limit=256*1024)
        require(clock()<deadline,'report-final-persistence-late')
    except BaseException:
        diagnostic.fence('report-final-persistence-unconfirmed')
        # The evidence step fails; never leave a successful-looking retained packet.
        REPORT.unlink(missing_ok=True)
        raise
    return report


def validate_state(value, source):
    fields={'schema','source','phase','status','reason','acceptance','interpretation','commands','product','contact',
        'sourceFiles','toolchain','runnerLocale','sandboxBefore','sandboxAfter','admissions','budget','jobClock','createdMonotonic','workDeadlineMonotonic','preparationDeadlineMonotonic'}
    require(isinstance(value,dict) and fields<=set(value)<=fields|{'evidenceStartedMonotonic','evidenceDeadlineMonotonic'},'unknown-state-fields')
    require(type(value['schema']) is int and value['schema']==1 and value['source']==source and value['acceptance'] is False and
        value['interpretation']==INTERPRETATION and value['budget']==BUDGET,'unbound-state')
    require(value['status'] in ('incomplete','test-closed','evidence-completed') and value['phase'] in ('preparation','xctest','evidence') and
        isinstance(value['reason'],str) and 0<len(value['reason'])<=160,'invalid-state-status')
    job=value['jobClock']
    require(isinstance(job,dict) and set(job)=={'schema','platform','minutes','started_epoch','started_monotonic','lane','sha','run_id','reserves','startup_margin'} and
        type(job['schema']) is int and job['schema']==1 and job['platform']==PLATFORM and job['minutes']==25 and job['lane']==PLATFORM and
        job['sha']==source['sha'] and job['run_id']==source['run'] and job['reserves']==RESERVES and job['startup_margin']==30 and
        number(job['started_epoch']) and number(job['started_monotonic']),'wrong-job-clock')
    require(all(number(value[k]) for k in ('createdMonotonic','workDeadlineMonotonic','preparationDeadlineMonotonic')) and
        job['started_monotonic']<=value['createdMonotonic']<value['preparationDeadlineMonotonic']<=value['workDeadlineMonotonic']<=job['started_monotonic']+1020 and
        value['preparationDeadlineMonotonic']<=value['createdMonotonic']+500,'invalid-phase-clock')
    has_evidence='evidenceStartedMonotonic' in value
    require(has_evidence==('evidenceDeadlineMonotonic' in value),'partial-evidence-clock')
    if has_evidence:
        start,end=value['evidenceStartedMonotonic'],value['evidenceDeadlineMonotonic']
        require(number(start) and number(end) and value['createdMonotonic']<=start<end<=min(start+180,job['started_monotonic']+1330),'invalid-evidence-clock')
    require(value['toolchain'] is None or value['toolchain']==TOOLCHAIN,'wrong-toolchain')
    require(value['sourceFiles']=={} or value['sourceFiles']=={p:digest(read_file(Path(p),1_000_000)) for p in SOURCES},'source-bytes-changed')
    if value['product'] is not None:
        product=value['product']; require(isinstance(product,dict) and set(product)=={'applicationPath','executable','executableSHA256','logicSHA256'} and
            isinstance(product['applicationPath'],str) and product['applicationPath'].startswith('/') and '..' not in Path(product['applicationPath']).parts and
            product['applicationPath'].endswith('/build/mac-sandbox/Build/Products/Debug/TouchColor.app') and
            product['executable']==product['applicationPath']+'/Contents/MacOS/TouchColor' and
            sha(product['executableSHA256']) and sha(product['logicSHA256']),'bad-product')
    if value['runnerLocale'] is not None:
        require(parse_runner_locale(encode(value['runnerLocale']))==value['runnerLocale'],'changed-runner-locale')
    for field in ('sandboxBefore','sandboxAfter'):
        require(value[field] is None or value[field]==MINIMAL_ENTITLEMENTS and all(x is True for x in value[field].values()),'changed-sandbox-entitlements')
    commands=value['commands'];expected=plan(value['contact'])
    require(isinstance(commands,list) and len(commands)<=len(expected),'unbounded-command-plan')
    prior=None
    for index,row in enumerate(commands):
        label,argv,seconds,minimum,cleanup,phase=expected[index]
        rowfields={'label','phase','argv','requestedSeconds','minimumSeconds','cleanupReserveSeconds','captureCap','startedMonotonic','startedEpoch',
            'deadlineMonotonic','cleanupDeadlineMonotonic','phaseCeilingMonotonic','returned','exit','cleanupConfirmed','timely','stdoutBytes','stderrBytes','stdoutSHA256','stderrSHA256'}
        require(isinstance(row,dict) and rowfields<=set(row)<=rowfields|{'finishedMonotonic','finishedEpoch'},'unknown-command-fields')
        require((row['label'],row['argv'],row['requestedSeconds'],row['minimumSeconds'],row['cleanupReserveSeconds'],row['phase'])==
            (label,argv,seconds,minimum,cleanup,phase) and row['captureCap']==(4096 if label=='runner-locale' else 512*1024),'changed-command-plan')
        ceiling=value['preparationDeadlineMonotonic'] if phase=='preparation' else (commands[TEST_INDEX]['deadlineMonotonic'] if index>TEST_INDEX else value['workDeadlineMonotonic']) if phase=='xctest' else value.get('evidenceDeadlineMonotonic')
        require(all(number(row[k]) for k in ('startedMonotonic','startedEpoch','deadlineMonotonic','cleanupDeadlineMonotonic','phaseCeilingMonotonic')) and
            row['phaseCeilingMonotonic']==ceiling and row['startedMonotonic']+minimum<=row['deadlineMonotonic']<=row['startedMonotonic']+seconds+.000001 and
            row['cleanupDeadlineMonotonic']==row['deadlineMonotonic']+cleanup and row['cleanupDeadlineMonotonic']<=ceiling+.000001 and
            value['createdMonotonic']<=row['startedMonotonic'] and (prior is None or prior<=row['startedMonotonic']),'changed-command-clock')
        require(type(row['returned']) is bool and type(row['timely']) is bool and (row['cleanupConfirmed'] is None or type(row['cleanupConfirmed']) is bool),'invalid-command-flags')
        if row['returned']:
            require(type(row['exit']) is int and -255<=row['exit']<=255 and row['cleanupConfirmed'] is True and
                number(row.get('finishedMonotonic')) and row['startedMonotonic']<=row['finishedMonotonic'] and
                number(row.get('finishedEpoch')) and row['startedEpoch']<=row['finishedEpoch'] and
                all(integer(row[k]) for k in ('stdoutBytes','stderrBytes')) and row['stdoutBytes']+row['stderrBytes']<=row['captureCap'] and
                all(sha(row[k]) for k in ('stdoutSHA256','stderrSHA256')) and
                row['timely']==(row['finishedMonotonic']<row['deadlineMonotonic']),'invalid-return-facts')
            prior=row['finishedMonotonic']
        else:
            require(row['timely'] is False and all(row[k] is None for k in ('exit','stdoutBytes','stderrBytes','stdoutSHA256','stderrSHA256')),'invented-interrupted-output')
            if row['cleanupConfirmed'] is True:
                require(number(row.get('finishedMonotonic')) and row['startedMonotonic']<=row['finishedMonotonic']<=row['cleanupDeadlineMonotonic'] and
                    number(row.get('finishedEpoch')) and row['startedEpoch']<=row['finishedEpoch'],'unbound-host-cleanup')
        if index<len(commands)-1 or value['status']!='incomplete':
            require(row['returned'] and row['timely'] and row['cleanupConfirmed'] is True and row['exit'] in ((0,65) if index==TEST_INDEX else (0,)),'continued-after-uncertainty')
            if index<5:
                outputs=[(source['sha']+'\n'+PARENT+'\n').encode(),b'',b'26A428\n',b'arm64\n',(TOOLCHAIN['xcode']+'\n').encode()]
                require(row['stdoutBytes']==len(outputs[index]) and row['stdoutSHA256']==digest(outputs[index]),'unbound-preflight-output')
        if index>=6: require(value['runnerLocale'] is not None and value['sourceFiles'] and value['toolchain']==TOOLCHAIN,'build-without-runner-locale')
        if index>=TEST_INDEX: require(value['product'] and value['sourceFiles'] and value['toolchain']==TOOLCHAIN and
            value['runnerLocale'] is not None and value['sandboxBefore']==MINIMAL_ENTITLEMENTS,'missing-test-preconditions')
        if index>=SUMMARY_INDEX: require(value['sandboxAfter']==value['sandboxBefore']==MINIMAL_ENTITLEMENTS,'missing-post-test-signature-proof')
        if index>=SUMMARY_INDEX: require(has_evidence and row['startedMonotonic']>=value['evidenceStartedMonotonic'],'evidence-outside-phase')
    require(isinstance(value['admissions'],list) and len(value['admissions'])<=16,'unbounded-admissions')
    # Every attempted command has one exact admission. One final failed admission
    # can follow, but can never spawn or grant a later phase.
    require(len(value['admissions']) in (len(commands),len(commands)+1),'missing-command-admission')
    for index,entry in enumerate(value['admissions']):
        require(index<len(expected),'unplanned-admission')
        label,_,seconds,minimum,cleanup,phase=expected[index]
        admission_fields={'phase','label','requested_seconds','minimum_seconds','cleanup_reserve_seconds','granted_seconds','remaining_seconds','admitted'}
        require(isinstance(entry,dict) and admission_fields<=set(entry)<=admission_fields|{'result'} and
            entry.get('phase')==('evidence' if phase=='evidence' else 'work') and entry.get('label')==label and
            entry.get('requested_seconds')==seconds and entry.get('minimum_seconds')==minimum and entry.get('cleanup_reserve_seconds')==cleanup and
            type(entry.get('admitted')) is bool and number(entry.get('granted_seconds')) and number(entry.get('remaining_seconds')) and
            0<=entry['granted_seconds']<=seconds and entry['remaining_seconds']>=0 and
            abs(entry['granted_seconds']-min(seconds,max(0,entry['remaining_seconds']-cleanup)))<=.002 and
            (entry['admitted'] or entry.get('result')=='not_started_insufficient_budget'),'invalid-admission')
        if index<len(commands):
            require(entry['admitted'] is True and entry['granted_seconds']>=minimum and
                commands[index]['deadlineMonotonic']-commands[index]['startedMonotonic']<=entry['granted_seconds']+.002,'unadmitted-command')
        else: require(value['status']=='incomplete','unexplained-final-admission')
    if value['contact'] is not None: require(len(commands)>=15,'contact-before-export')
    if value['status']=='test-closed': require(len(commands)==13 and value['phase']=='xctest','incomplete-test-closure')
    if value['status']=='evidence-completed': require(len(commands)==15 and value['contact'] is not None and value['phase']=='evidence','incomplete-evidence-closure')
    return value


def validate_packet(root,source):
    report=strict_json(read_file(root/'mac-chinese-contact.json',256*1024))
    fields={'schema','source','acceptance','interpretation','status','reason','contactOutcome','files','otherAttachments',
        'route','requestedLocalization','singleChineseSandboxContactQualification','runnerLocale','appLanguageObservation',
        'evidenceStartedMonotonic','evidenceDeadlineMonotonic','elapsedSeconds'}
    require(isinstance(report,dict) and set(report)==fields and type(report['schema']) is int and report['schema']==1 and
        report['source']==source and report['acceptance'] is False and report['interpretation']==INTERPRETATION and
        report['otherAttachments']=='not-retained' and report['route']=='Chinese-sandbox-test-plan' and
        report['requestedLocalization']==LOCALIZATION,'unbound-report')
    require(report['status'] in ('incomplete','contact-observed') and report['contactOutcome'] in ('unknown','failed','passed') and
        isinstance(report['reason'],str) and 0<len(report['reason'])<=160,'invalid-report-status')
    require(isinstance(report['files'],dict) and 1<=len(report['files'])<=10,'bad-file-count')
    allowed={'state.json','runner-locale.json','uncertain.json','mac-ui-summary.json','screenshots/manifest.json','sandbox-before.plist','sandbox-after.plist'}
    total=0
    for path in root.rglob('*'):
        require(not path.is_symlink(),'linked-evidence')
        if path.is_dir(): continue
        name=path.relative_to(root).as_posix()
        require(name=='mac-chinese-contact.json' or name in report['files'],'unlisted-evidence')
        raw=read_file(path,LIMIT); total+=len(raw)
        if name in report['files']:
            require(name in allowed or re.fullmatch('screenshots/[0-9A-Fa-f-]{36}\\.txt',name),'unapproved-file')
            require(report['files'][name]==dict(bytes=len(raw),sha256=digest(raw)),'changed-evidence-bytes')
    require(total<=LIMIT and set(report['files'])=={p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}-{'mac-chinese-contact.json'},'packet-cap-or-missing-file')
    value=validate_state(strict_json(read_file(root/'state.json',128*1024)),source)
    require(report['evidenceStartedMonotonic']==value.get('evidenceStartedMonotonic') and
        report['evidenceDeadlineMonotonic']==value.get('evidenceDeadlineMonotonic') and number(report['elapsedSeconds']) and
        0<=report['elapsedSeconds']<report['evidenceDeadlineMonotonic']-report['evidenceStartedMonotonic'] and
        report['evidenceDeadlineMonotonic']<=report['evidenceStartedMonotonic']+180,'changed-evidence-phase')
    require(all(report['evidenceStartedMonotonic']+report['elapsedSeconds']>=row['finishedMonotonic']
        for row in value['commands'][SUMMARY_INDEX:] if 'finishedMonotonic' in row),'evidence-ended-before-command')
    if 'uncertain.json' in report['files']:
        fence=strict_json(read_file(root/'uncertain.json',16384))
        require(isinstance(fence,dict) and set(fence)=={'schema','source','phase','reason'} and type(fence['schema']) is int and
            fence['schema']==1 and fence['source']==source and fence['phase']==value['phase'] and fence['reason']==value['reason'] and
            value['status']=='incomplete','unbound-uncertainty-fence')
    require(report['runnerLocale']==value['runnerLocale'],'runner-locale-report-mismatch')
    if value['runnerLocale'] is not None:
        raw_locale=read_file(root/'runner-locale.json',4096);locale_command=value['commands'][5]
        require(locale_command['returned'] and locale_command['timely'] and locale_command['cleanupConfirmed'] is True and
            locale_command['exit']==0 and locale_command['stdoutBytes']==len(raw_locale) and locale_command['stdoutSHA256']==digest(raw_locale) and
            parse_runner_locale(raw_locale)==value['runnerLocale'],'unbound-runner-locale')
    else:require('runner-locale.json' not in report['files'],'invented-runner-locale')
    for field,name,index in [('sandboxBefore','sandbox-before.plist',9),('sandboxAfter','sandbox-after.plist',12)]:
        if value[field] is None:require(name not in report['files'],'invented-entitlement-readback');continue
        raw=read_file(root/name,4096);command=value['commands'][index]
        require(command['returned'] and command['timely'] and command['cleanupConfirmed'] is True and command['exit']==0 and
            command['stdoutBytes']==len(raw) and command['stdoutSHA256']==digest(raw) and parse_entitlements(raw)==value[field],'unbound-entitlement-readback')
    if value['contact'] is not None:
        contact=closed_contact(value,root)
        require(contact==value['contact'] and report['contactOutcome']==contact['outcome'],'changed-original-outcome')
    else:
        require(report['contactOutcome']=='unknown','invented-contact-outcome')
    summary=strict_json(read_file(root/'mac-ui-summary.json',512*1024)) if value['contact'] else {}
    require(report['appLanguageObservation']==app_language_observation(summary,value['contact']),'invented-app-language')
    require(report['singleChineseSandboxContactQualification'] is (report['status']=='contact-observed' and report['contactOutcome']=='passed'),'changed-contact-qualification')
    if report['status']=='contact-observed':
        require(value['status']=='evidence-completed' and 'uncertain.json' not in report['files'] and
            report['reason']=='original-Chinese-contact-result','incomplete-contact-upgraded')
    else: require(value['status']=='incomplete','incomplete-report-contradiction')
    return report


def console(value,durable_state):
    row=dict(source=value.get('source',{}).get('sha'),run=value.get('source',{}).get('run'),attempt=value.get('source',{}).get('attempt'),
        phase=value.get('phase','evidence'),status=value.get('status','incomplete'),durability='file-and-directory-fsync' if durable_state else 'unconfirmed')
    raw=b'MAC_CHINESE_CONTACT '+encode(row)
    if len(raw)>512:return
    try:
        fd=sys.stdout.fileno();os.set_blocking(fd,False);os.write(fd,raw)
    except (OSError,ValueError):pass


def validate_once(budget,source,clock=time.monotonic):
    require(not VALIDATED.exists() and not VALIDATION_ATTEMPT.exists(),'validation-already-attempted')
    require(budget.remaining('validation')>=60,'validation-reserve-exhausted')
    began=clock(); deadline=min(began+60,began+budget.remaining('validation'))
    attempt=dict(schema=1,source=source,validationStartedMonotonic=began,validationDeadlineMonotonic=deadline)
    durable(VALIDATION_ATTEMPT,attempt)
    require(clock()<deadline,'validation-attempt-persistence-late')
    value=validate_packet(EVIDENCE,source)
    raw=read_file(REPORT,256*1024)
    require(clock()<deadline,'validation-late')
    receipt=dict(schema=1,source=source,reportSHA256=digest(raw),status=value['status'],contactOutcome=value['contactOutcome'],
        acceptance=False,validationStartedMonotonic=began,checkedMonotonic=clock(),validationDeadlineMonotonic=deadline)
    try:
        durable(VALIDATED,receipt)
        require(clock()<deadline,'validation-receipt-late')
    except BaseException:
        VALIDATED.unlink(missing_ok=True)
        raise
    return value


def contact_result(budget,source,clock=time.monotonic):
    # Only bounded file/hash checks in the original 20-second overhead reserve;
    # the full validator runs once in its separate 60-second phase.
    began=clock(); deadline=min(began+20,budget.hard_deadline)
    require(began<deadline,'outcome-guard-late')
    receipt=strict_json(read_file(VALIDATED,16384)); raw=read_file(REPORT,256*1024)
    attempt=strict_json(read_file(VALIDATION_ATTEMPT,16384))
    fields={'schema','source','reportSHA256','status','contactOutcome','acceptance','validationStartedMonotonic','checkedMonotonic','validationDeadlineMonotonic'}
    require(isinstance(receipt,dict) and set(receipt)==fields and type(receipt['schema']) is int and receipt['schema']==1 and
        receipt['source']==source and receipt['reportSHA256']==digest(raw) and receipt['acceptance'] is False and
        receipt['status'] in ('incomplete','contact-observed') and receipt['contactOutcome'] in ('unknown','failed','passed'),'unbound-validated-outcome')
    require(all(number(receipt[k]) for k in ('validationStartedMonotonic','checkedMonotonic','validationDeadlineMonotonic')) and
        receipt['validationStartedMonotonic']<=receipt['checkedMonotonic']<receipt['validationDeadlineMonotonic']<=receipt['validationStartedMonotonic']+60 and
        receipt['checkedMonotonic']<=began,'invalid-validation-clock')
    require(attempt==dict(schema=1,source=source,validationStartedMonotonic=receipt['validationStartedMonotonic'],
        validationDeadlineMonotonic=receipt['validationDeadlineMonotonic']),'changed-validation-attempt')
    value=strict_json(raw)
    require(value['source']==source and value['acceptance'] is False and value['status']==receipt['status'] and
        value['contactOutcome']==receipt['contactOutcome'] and clock()<deadline,'changed-or-late-final-outcome')
    return 0 if receipt['status']=='contact-observed' and receipt['contactOutcome']=='passed' else 1


def require_fresh_run():
    require(not any(path.exists() or path.is_symlink() for path in (STATE,LATCH,REPORT,VALIDATED,VALIDATION_ATTEMPT,RESULT)) and
        not EVIDENCE.exists() and not EVIDENCE.is_symlink() and not any(ROOT.iterdir()),'stale-run')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['run','evidence','validate','contact-result']);args=parser.parse_args()
    source=source_identity(os.environ);budget=load_budget()
    require(budget.record['platform']==PLATFORM and budget.record['lane']==PLATFORM and budget.record['minutes']==25,'wrong-budget')
    require(all(not p.is_symlink() for p in (ROOT,*ROOT.parents)),'unsafe-root')
    ROOT.mkdir(parents=True,exist_ok=True)
    if args.action=='run':
        require_fresh_run()
        diagnostic=Diagnostic(budget,source);value=diagnostic.run();console(value,diagnostic.durable_state)
        return 0 if value['status']=='test-closed' else 1
    if args.action=='evidence':
        value=evidence(budget,source);console(value,True);return 0
    if args.action=='contact-result':
        return contact_result(budget,source)
    value=validate_once(budget,source)
    console(value,True);return 0


if __name__=='__main__':raise SystemExit(main())
