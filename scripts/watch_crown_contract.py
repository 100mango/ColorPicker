"""Exact, deliberately separate one-profile diagnostic contract; no acceptance alias."""
from pathlib import Path
import hashlib
import re

PLATFORM = 'watch-crown-control'
LANE = 'watch-crown-control-smallest'
REF = 'refs/heads/codex/watch-crown-diagnostic'
WORKFLOW = '.github/workflows/watch-crown-control.yml'
PHASES = {'preflight': 30, 'builds': 240, 'setup': 600,
          'actual_cold': 240, 'isolated_static': 180, 'rgb_positive': 180}
CAP = 1_200_000
OBS_CAP = 32_768
METHODS = (
    {'key': 'actual_cold', 'project': 'TouchColorWatch', 'target': 'TouchColorWatchUITests',
     'case': 'WatchWorkflowTests/testHomeListDigitalCrownFromColdLaunch', 'derived_data': 'build/crown-product',
     'bundle_id': 'com.mango.touchColor.watchkitapp'},
    {'key': 'isolated_static', 'project': 'TouchColorWatchCrownControl', 'target': 'TouchColorWatchCrownControlUITests',
     'case': 'WatchStaticCrownControlTests/testStaticListDigitalCrownThreeRotations', 'derived_data': 'build/crown-static',
     'bundle_id': 'com.mango.touchColor.watchCrownControl'},
    {'key': 'rgb_positive', 'project': 'TouchColorWatch', 'target': 'TouchColorWatchUITests',
     'case': 'WatchWorkflowTests/testRealDigitalCrownChangesRGBComponent', 'derived_data': 'build/crown-product',
     'bundle_id': 'com.mango.touchColor.watchkitapp'},
)


def require(condition, reason):
    if not condition: raise ValueError(reason)


def binding(env):
    require(env.get('GITHUB_EVENT_NAME') == 'push', 'Dedicated source push required')
    require(env.get('GITHUB_REPOSITORY') == '100mango/ColorPicker', 'Wrong repository')
    require(env.get('GITHUB_REF') == REF, 'Diagnostic branch only; main and canonical cohort refs forbidden')
    sha = env.get('GITHUB_SHA', '')
    require(re.fullmatch('[0-9a-f]{40}', sha), 'Missing exact source SHA')
    require(env.get('GITHUB_WORKFLOW_SHA') == sha, 'Workflow/source mismatch')
    require(env.get('TOUCHCOLOR_JOB_PLATFORM') == PLATFORM and env.get('TOUCHCOLOR_JOB_LANE') == LANE
            and env.get('TOUCHCOLOR_JOB_MINUTES') == '25', 'Wrong dedicated budget identity')
    require(env.get('TOUCHCOLOR_WATCH_PROFILE') == 'smallest' and env.get('TOUCHCOLOR_TEXT_PHASE') == 'normal', 'Wrong profile/text phase')
    require(env.get('DEVELOPER_DIR') == '/Applications/Xcode_27.app/Contents/Developer' and env.get('RUNNER_ARCH') == 'ARM64', 'Wrong toolchain/runner architecture')
    require(env.get('TOUCHCOLOR_MAX_EVIDENCE_BYTES') == str(CAP), 'Evidence cap changed')
    require(re.fullmatch('[1-9][0-9]*', env.get('GITHUB_RUN_ID', '')) and re.fullmatch('[1-9][0-9]*', env.get('GITHUB_RUN_ATTEMPT', '')), 'Missing run identity')
    return {'sha': sha, 'ref': REF,
            'repository': env['GITHUB_REPOSITORY'], 'run_id': env['GITHUB_RUN_ID'],
            'attempt': env['GITHUB_RUN_ATTEMPT']}


def test_command(method, device):
    require(re.fullmatch('[0-9A-Fa-f-]{36}', device), 'Invalid destination UUID')
    name = method['project']
    return ['xcodebuild', 'test-without-building', '-project', name+'.xcodeproj', '-scheme', name,
            '-configuration', 'Debug', '-destination', 'platform=watchOS Simulator,id='+device,
            '-derivedDataPath', method['derived_data'], '-parallel-testing-enabled', 'NO',
            '-maximum-concurrent-test-simulator-destinations', '1', '-collect-test-diagnostics', 'never',
            '-test-timeouts-enabled', 'YES', '-default-test-execution-time-allowance', '120',
            '-maximum-test-execution-time-allowance', '120',
            '-resultBundlePath', 'build/watch-crown-'+method['key']+'.xcresult',
            '-only-testing:'+method['target']+'/'+method['case'], 'ARCHS=arm64', 'CODE_SIGNING_ALLOWED=NO']


def method_scheduling_status(method, device, source_sha, stage, summary, lifecycle):
    """Controller-only continuation guard, separate from the final validator.

    Counts alone are not case completion. Reconcile this exact invocation's
    source, destination, real exit, lifecycle and finalized summary before any
    independent control may start. The return value is diagnostic, not acceptance.
    """
    import math
    def number(value):return type(value) in (int,float) and math.isfinite(value)
    require(stage.get('command')==test_command(method,device) and stage.get('source_sha')==source_sha,
            'Summary command/source binding mismatch')
    require(stage.get('started') is True and stage.get('timed_out') is False and stage.get('stdout_truncated') is False
            and stage.get('process_group_gone') is True and stage.get('capture_reader_finished') is True,
            'Test command was incomplete or cleanup unconfirmed')
    raw_exit=stage.get('raw_exit')
    require(type(raw_exit) is int and raw_exit in (0,65) and stage.get('exit')==raw_exit,
            'Missing genuine terminal test exit')
    status='passed' if raw_exit==0 else 'failed'
    keys=('passedTests','failedTests','skippedTests','expectedFailures')
    require(isinstance(summary,dict) and all(type(summary.get(k)) is int and summary[k]>=0 for k in keys),
            'Missing exact summary counts')
    counts={k:summary[k] for k in keys}
    expected={'passedTests':int(status=='passed'),'failedTests':int(status=='failed'),'skippedTests':0,'expectedFailures':0}
    require(counts==expected and type(summary.get('totalTestCount')) is int and summary['totalTestCount']==1
            and summary.get('result')==status.title(),'Summary counts/result contradict original command exit')
    rows=summary.get('devicesAndConfigurations')
    require(isinstance(rows,list) and len(rows)==1 and isinstance(rows[0],dict),'Ambiguous summary destination/configuration')
    row=rows[0]
    require(all(type(row.get(k)) is int and row[k]==counts[k] for k in keys),'Destination counts contradict summary')
    actual=row.get('device')
    require(isinstance(actual,dict) and all(actual.get(k)==v for k,v in
            {'deviceId':device,'platform':'watchOS Simulator','osVersion':'27.0','architecture':'arm64'}.items()),
            'Summary belongs to another device/runtime/architecture')
    require(row.get('testPlanConfiguration')=={'configurationId':'1','configurationName':'Test Scheme Action'},
            'Summary belongs to another test configuration')
    start,finish=summary.get('startTime'),summary.get('finishTime')
    ss,sf=stage.get('started_epoch'),stage.get('finished_epoch')
    sm,fm=stage.get('started_monotonic'),stage.get('finished_monotonic')
    require(all(number(v) for v in (start,finish,ss,sf,sm,fm)) and ss<=start<finish<=sf and sm<fm
            and fm-sm<180 and sf-ss<180 and abs((sf-ss)-(fm-sm))<=1,
            'Summary is stale or outside the exact command lifetime')
    target=method['target'];cls,member=method['case'].split('/')
    prefix="Test Case '-["+target+'.'+cls+' '+member+"]' "
    lines=lifecycle.splitlines()
    require(len(lines)==2 and lines[0]==prefix+'started.','Missing, duplicate or foreign case lifecycle')
    matched=re.fullmatch(re.escape(prefix)+r'(passed|failed) \(([0-9]+(?:\.[0-9]+)?) seconds\)\.',lines[1])
    require(matched is not None and matched[1]==status,'Lifecycle result contradicts command/summary')
    duration=float(matched[2]);require(0<=duration<120 and duration<=finish-start+0.001,
                                       'Case duration exceeds execution allowance or summary lifetime')
    failures=summary.get('testFailures')
    require(isinstance(failures,list) and bool(failures)==(status=='failed'),'Missing or contradictory failure diagnostics')
    for failure in failures:
        require(isinstance(failure,dict) and failure.get('targetName')==target
                and failure.get('testIdentifierString')==method['case']+'()'
                and failure.get('testIdentifierURL')=='test://com.apple.xcode/'+method['project']+'/'+target+'/'+method['case']
                and isinstance(failure.get('failureText'),str) and bool(failure['failureText']),
                'Summary failure belongs to another case or target')
    return status
