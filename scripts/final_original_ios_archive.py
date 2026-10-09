#!/usr/bin/env python3
"""Closed exact-source adapter for the existing unsigned TouchColor archive proof.

The product checkout is independently pinned. Historical archive admission is
untouched; its bounded package, archive, UUID and retention functions are reused.
"""
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time

CONTROL_ROOT = Path(__file__).resolve().parents[1]
PRODUCT_ROOT = CONTROL_ROOT.parent / 'product'
SOURCE = '922eb296e3b2417a414b72ad4eb2dddeb534328f'
TREE = '4974b9ac597a75ef30dcf92be143da1441801db2'
CONFIG = '.github/final-original-ios-archive.json'
WORKFLOW = '.github/workflows/ios-original-archive.yml'
BRANCH = 'refs/heads/ios-original-archive'
CONTROL_CHANGES = sorted(['M\t' + WORKFLOW, 'A\t' + CONFIG,
    'A\tscripts/final_original_ios_archive.py', 'A\tscripts/test_final_original_ios_archive.py'])


def need(value, reason):
    if not value:
        raise ValueError(reason)


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            need(key not in result, 'duplicate-control-key')
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=pairs)


def validate_control(value, *, require_enabled=True):
    need(isinstance(value, dict) and set(value) == {'schema', 'enabled', 'source', 'native_gate', 'execution_scope'}, 'control-fields')
    need(type(value['schema']) is int and value['schema'] == 1 and type(value['enabled']) is bool, 'control-schema')
    need(value['source'] == {'commit': SOURCE, 'tree': TREE, 'version': '2.0.1', 'build': '20002'}, 'product-source-mismatch')
    native = value['native_gate']
    need(isinstance(native, dict) and set(native) == {'status', 'source_commit', 'run_id', 'artifacts'}, 'native-fields')
    need(native['source_commit'] == SOURCE, 'native-source-mismatch')
    need(value['execution_scope'] == 'unsigned-package-diagnostic', 'diagnostic-scope-required')
    # Native UI qualification is deliberately a separate later release gate.
    # This route can establish package facts but can never issue release approval.
    need(native['status'] == 'pending' and native['run_id'] is None and native['artifacts'] == {},
         'diagnostic-cannot-claim-native-qualification')
    if require_enabled:
        need(value['enabled'] is True, 'archive-control-closed')
    else:
        need(value['enabled'] is False, 'template-must-remain-closed')
    return value


def read_control(root=CONTROL_ROOT):
    path = root / CONFIG
    info = path.lstat()
    need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size <= 16384, 'control-file-invalid')
    raw = path.read_bytes()
    need(len(raw) == info.st_size, 'control-file-changed')
    return strict_json(raw), hashlib.sha256(raw).hexdigest()


def admit_sources(value, env, git):
    validate_control(value)
    expected = {'GITHUB_REPOSITORY': '100mango/ColorPicker', 'GITHUB_REF': BRANCH,
        'GITHUB_WORKFLOW_REF': '100mango/ColorPicker/' + WORKFLOW + '@' + BRANCH,
        'GITHUB_JOB': 'archive', 'GITHUB_RUN_ATTEMPT': '1',
        'DEVELOPER_DIR': '/Applications/Xcode_27.app/Contents/Developer'}
    need(all(env.get(key) == item for key, item in expected.items()), 'archive-job-identity')
    need(env.get('GITHUB_EVENT_NAME') in ('push', 'workflow_dispatch'), 'archive-event')
    head = env.get('GITHUB_SHA', '')
    need(re.fullmatch(r'[0-9a-f]{40}', head) is not None and env.get('GITHUB_WORKFLOW_SHA') == head,
         'control-workflow-source-mismatch')
    need(re.fullmatch(r'[1-9][0-9]*', env.get('GITHUB_RUN_ID', '')) is not None, 'archive-run-identity')
    need(git('control', 'rev-parse', 'HEAD') == head, 'control-head-mismatch')
    need(git('control', 'rev-list', '--parents', '-n', '1', 'HEAD').split() == [head, SOURCE], 'control-sole-parent')
    need(git('control', 'rev-parse', SOURCE + '^{tree}') == TREE, 'control-product-tree')
    need(sorted(git('control', 'diff', '--name-status', SOURCE, 'HEAD', '--').splitlines()) == CONTROL_CHANGES,
         'control-source-scope')
    for label in ('control', 'product'):
        need(git(label, 'status', '--porcelain', '--untracked-files=all') == '', label + '-checkout-dirty')
    need(git('product', 'rev-parse', 'HEAD') == SOURCE and git('product', 'rev-parse', 'HEAD^{tree}') == TREE,
         'product-checkout-mismatch')
    return {**expected, 'GITHUB_SHA': head, 'GITHUB_WORKFLOW_SHA': head,
        'GITHUB_EVENT_NAME': env['GITHUB_EVENT_NAME'], 'GITHUB_RUN_ID': env['GITHUB_RUN_ID'],
        'control_sha': head, 'product_sha': SOURCE, 'product_tree': TREE, 'native_gate': value['native_gate']}


def checked_api(env, control=CONTROL_ROOT, product=PRODUCT_ROOT, *, deadline):
    # Only bounded local Git reads precede importing any source-owned Python.
    value, digest = read_control(control)
    def git(label, *args):
        remaining = deadline - time.monotonic()
        need(remaining > 1, 'admission-deadline')
        path = control if label == 'control' else product
        need(path.is_dir() and not path.is_symlink(), 'checkout-missing-or-linked')
        result = subprocess.run(['git', '--no-pager', '-C', str(path), *args],
            capture_output=True, timeout=min(5, remaining), check=True)
        need(len(result.stdout) <= 262144 and len(result.stderr) <= 8192, 'git-output-limit')
        return result.stdout.decode().strip()
    binding = admit_sources(value, env, git)
    sys.path.insert(0, str(product / 'scripts'))
    api = importlib.import_module('original_ios_archive')
    need(Path(api.__file__).resolve() == (product / 'scripts/original_ios_archive.py').resolve(), 'archive-module-origin')
    return api, {**binding, 'control_manifest_sha256': digest}


def execute(api, initial, env, control=CONTROL_ROOT, product=PRODUCT_ROOT, *, began, clock=time.monotonic):
    receipts = []; phase = 'prepare'; phase_deadline = began + api.PHASE_END['prepare']
    report = {'schema': 1, 'scope': 'final-original-ios-unsigned-package-diagnostic', 'qualified': False,
        'release_qualified': False, 'native_ui_qualified': False,
        'signing_qualified': False, 'store_qualified': False, 'older_os_qualified': False,
        'ui_qualification_separate': True, 'binary_handoff': False, 'commands': receipts,
        'upload_qualified': False, 'qualification_scope': 'archive-observation-before-retention',
        'clock': {'started_monotonic': began, 'phase_end_seconds': api.PHASE_END,
                  'report_ready_deadline': began + api.PHASE_END['final_source_pack']},
        'host_scope': 'owned-client-and-process-group observation; no daemon lifetime claim'}
    def run(argv, **kwargs):
        return api.command(argv, deadline=phase_deadline, receipts=receipts, clock=clock, **kwargs)
    def identity():
        value, digest = read_control(control)
        def git(label, *args):
            path = control if label == 'control' else product
            return run(['git', '--no-pager', '-C', str(path), *args], seconds=5, cap=262144).decode().strip()
        binding = {**admit_sources(value, env, git), 'control_manifest_sha256': digest}
        need(binding == initial, 'source-or-control-changed')
        binding['app_graph'] = api.package.source_graph(product)
        scheme = api.ET.fromstring((product / 'TouchColor.xcodeproj/xcshareddata/xcschemes/TouchColor.xcscheme').read_bytes())
        need(scheme.find('ArchiveAction').get('buildConfiguration') == 'Release', 'archive-configuration')
        entries = [entry.find('BuildableReference') for entry in scheme.findall('./BuildAction/BuildActionEntries/BuildActionEntry')
                   if entry.get('buildForArchiving') == 'YES']
        need(len(entries) == 1 and entries[0].get('BuildableName') == 'TouchColor.app' and
             entries[0].get('BlueprintName') == 'TouchColor' and
             entries[0].get('ReferencedContainer') == 'container:TouchColor.xcodeproj', 'archive-scheme')
        return binding
    try:
        need(not (product / 'build').exists() and not (product / 'build').is_symlink(), 'output-not-fresh')
        (product / 'build').mkdir()
        report['owned_output'] = api.file_identity((product / 'build').lstat())[:2]
        report['source_before'] = identity()
        report['toolchain'] = {'os': run(['sw_vers'], seconds=5, cap=4096).decode(),
            'xcode': run(['xcodebuild', '-version'], seconds=10, cap=4096).decode(),
            'sdks': run(['xcodebuild', '-showsdks'], seconds=15, cap=16384).decode()}
        need(report['toolchain']['xcode'].strip().splitlines() == ['Xcode 27.0', 'Build version 27A266a'], 'toolchain-mismatch')
        need('iphoneos27.0' in report['toolchain']['sdks'], 'sdk-mismatch')
        for optimize in ([], ['-O']):
            run([sys.executable, *optimize, '-S', '-m', 'unittest', 'discover', '-s', 'scripts',
                 '-p', 'test_*original_ios*.py'], seconds=40, cap=65536)
        run([sys.executable, '-S', 'scripts/verify_original_design_source.py'], seconds=10, cap=16384)
        api.timely(began + api.PHASE_END['prepare'], clock)
        phase = 'archive'; phase_deadline = min(began + api.PHASE_END[phase], clock() + 620)
        run(api.ARCHIVE_COMMAND, seconds=600, cap=512 * 1024, cleanup=10)
        phase = 'proof'; phase_deadline = min(began + api.PHASE_END[phase], clock() + 110)
        report['proof'] = api.verify_archive(product / api.ARCHIVE, run, phase_deadline, root=product, clock=clock)
        phase = 'final_source_pack'; phase_deadline = min(began + api.PHASE_END[phase], clock() + 30)
        report['clock']['report_ready_deadline'] = phase_deadline
        report['source_after'] = identity()
        need(report['source_after'] == report['source_before'], 'source-changed')
        api.timely(phase_deadline, clock); report['qualified'] = True
    except (Exception, KeyboardInterrupt) as error:
        report['clock']['report_ready_deadline'] = min(report['clock']['report_ready_deadline'], clock() + 30)
        report['failure'] = {'phase': phase, 'type': type(error).__name__, 'reason': str(error)[:4096]}
    report['clock']['elapsed_seconds'] = clock() - began
    return report


def main():
    began = time.monotonic(); env = dict(os.environ)
    api, binding = checked_api(env, deadline=began + 60)
    os.chdir(PRODUCT_ROOT)
    if len(sys.argv) == 2 and sys.argv[1] in ('admit-upload', 'finish-upload'):
        return api.upload_gate(sys.argv[1], root=PRODUCT_ROOT, env=env)
    need(len(sys.argv) == 1, 'no-input-selectors')
    result = execute(api, binding, env, began=began)
    if 'owned_output' not in result:
        print(json.dumps(result, default=api.json_value)); return 1
    need(stat.S_ISDIR((PRODUCT_ROOT / 'build').lstat().st_mode) and
         api.file_identity((PRODUCT_ROOT / 'build').lstat())[:2] == result['owned_output'], 'output-ownership-changed')
    decoded = api.retain_report(result, PRODUCT_ROOT / 'build/archive-proof', Path(env['GITHUB_OUTPUT']))
    print(json.dumps({'archive_qualified': decoded['qualified'], 'release_qualified': False,
                      'native_ui_qualified': False, 'failure': decoded.get('failure')}))
    return 0 if decoded['qualified'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
