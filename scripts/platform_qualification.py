#!/usr/bin/env python3
"""Closed admission only; all native execution and acceptance stay in existing scripts."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys

REPOSITORY = '100mango/ColorPicker'
REF = 'refs/heads/touchcolor-platform-qualification'
WORKFLOW = '.github/workflows/platform-qualification.yml'
WORKFLOW_REF = REPOSITORY + '/' + WORKFLOW + '@' + REF
CONFIG = '.github/platform-qualification.json'
MAX_CONTROL_COMMITS = 32
OVERLAY_PATHS = {
    WORKFLOW,
    CONFIG,
    'scripts/platform_qualification.py',
    'scripts/test_platform_qualification.py',
    'scripts/retain_mac_evidence.py',
    'scripts/test_retain_mac_evidence.py',
    'PLATFORM-QUALIFICATION.md',
}
MAC_IDENTITY = """    ('100mango/ColorPicker', 'refs/heads/touchcolor-platform-qualification',
     '100mango/ColorPicker/.github/workflows/platform-qualification.yml@refs/heads/touchcolor-platform-qualification'):
        ('.github/workflows/platform-qualification.yml', ('push',)),
"""
MAC_IDENTITY_TEST_EDITS = (
    ('test_only_two_exact_workflow_identities_and_original_events_are_admitted',
     'test_three_exact_workflow_identities_preserve_original_events'),
    ('self.assertEqual(len(keep.WORKFLOW_IDENTITIES), 2)',
     'self.assertEqual(len(keep.WORKFLOW_IDENTITIES), 3)'),
)
LANES = (
    'tv', 'mac', 'vision-chinese', 'vision-corrupt-audit', 'vision-canvas-audit',
    'vision-paste-relaunch', 'vision-png-export', 'vision-json-export', 'vision-photos',
    'vision-cancel', 'vision-files-select', 'vision-chinese-system-largest',
    'vision-canvas-audit-system-largest', 'ios', 'watch-smallest', 'watch-largest',
    'watch-smallest-system-largest', 'watch-largest-system-largest', 'paired',
)
DEFERRED = {
    'mac_sandbox': 'Not run: strict unsigned scope excludes test_mac_sandbox.sh and its ad-hoc signatures. The original full Mac evidence gate remains incomplete.',
    'ios': 'Not run here: the corrected iOS native gate is owned separately.',
    'watch_container_and_paired_transport': 'Not qualified: corrected iOS Watch embedding and paired foreground/background transport remain separate open gates.',
    'distribution': 'No archive/export, real signing, notarization, Store submission, physical camera/radio, or Intel runtime qualification.',
}


def require(value, message):
    if not value:
        raise ValueError(message)


def git(*args):
    value = subprocess.check_output(['git', *args], text=True, timeout=15)
    return value if args[0] == 'show' else value.strip()


def rows():
    """Read only the existing flat, source-owned matrix inventory; reject schema drift."""
    source = Path('.github/workflows/apple-platforms.yml').read_text()
    block = source.split('  native-platform:\n', 1)[1].split('        include:\n', 1)[1].split('    runs-on:', 1)[0]
    inventory = []
    for line in block.splitlines():
        match = re.fullmatch(r'          - (platform): ([a-z]+)|            ([a-z_]+): ([a-z0-9-]+)', line)
        require(match is not None, 'Native matrix shape changed; review its inventory explicitly')
        if match[1]:
            inventory.append({match[1]: match[2]})
        else:
            key, value = match[3], match[4]
            require(key not in inventory[-1], 'Duplicate native row field')
            inventory[-1][key] = int(value) if key in ('minutes', 'evidence_bytes') else value
    require(tuple(row.get('lane', row['platform']) for row in inventory) == LANES,
            'Native row inventory changed; do not silently omit a lane')
    return inventory


def select(lane):
    require(lane not in ('ios', 'paired'), 'Legacy iOS/paired row is deferred, never a corrected-source qualification')
    selected = [row for row in rows() if row.get('lane', row['platform']) == lane]
    require(len(selected) == 1, 'Select exactly one explicit existing native row')
    return selected[0]


def configuration(*, require_ready=True):
    def unique(items):
        value = {}
        for key, item in items:
            require(key not in value, 'Duplicate qualification config key')
            value[key] = item
        return value
    path = Path(CONFIG)
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= 4096, 'Unsafe or oversized qualification config')
    config = json.loads(path.read_text(), object_pairs_hook=unique)
    require(set(config) == {'schema', 'READY', 'corrected_product_sha', 'corrected_product_tree', 'selected_lane'}, 'Unexpected qualification config fields')
    require(type(config['schema']) is int and config['schema'] == 1 and type(config['READY']) is bool, 'Invalid qualification readiness/schema')
    if require_ready:
        require(config['READY'], 'Qualification is closed: READY must be explicitly true after corrected-source review and capacity check')
    if config['READY']:
        require(all(isinstance(config[key], str) and re.fullmatch('[0-9a-f]{40}', config[key]) for key in ('corrected_product_sha', 'corrected_product_tree')),
                'Corrected product SHA/tree must be bound to exact lowercase values')
    return config


SELECTION_START = '    # BEGIN LOCAL QUALIFICATION SELECTION\n'
SELECTION_END = '    # END LOCAL QUALIFICATION SELECTION\n'


def selection_block(config):
    if config['READY']:
        row = select(config['selected_lane'])
        condition = "${{ github.event_name == 'push' && github.ref == 'refs/heads/touchcolor-platform-qualification' }}"
    else:
        row = {'platform': 'unselected', 'minutes': 1, 'evidence_bytes': 0}
        condition = '${{ false }}'
    lines = [SELECTION_START.rstrip('\n'), '    if: ' + condition, '    strategy:',
             '      fail-fast: false', '      max-parallel: 1', '      matrix:', '        include:']
    for index, (key, value) in enumerate(row.items()):
        lines.append(('          - ' if index == 0 else '            ') + key + ': ' + str(value))
    return '\n'.join(lines) + '\n' + SELECTION_END


def render_selection(workflow, config):
    require(workflow.count(SELECTION_START) == 1 and workflow.count(SELECTION_END) == 1, 'Missing or duplicate generated selection boundaries')
    before, tail = workflow.split(SELECTION_START, 1)
    old, after = tail.split(SELECTION_END, 1)
    return before + selection_block(config) + after


def prepare():
    config = configuration(require_ready=False)
    path = Path(WORKFLOW)
    path.write_text(render_selection(path.read_text(), config))
    print('Prepared exactly one source-owned native row.' if config['READY'] else 'Prepared closed, unselected native job; no activation.')


def admit(environ=None):
    env = os.environ if environ is None else environ
    config = configuration()
    require(env.get('GITHUB_REPOSITORY') == REPOSITORY and env.get('GITHUB_REF') == REF
            and env.get('GITHUB_WORKFLOW_REF') == WORKFLOW_REF
            and env.get('GITHUB_EVENT_NAME') == 'push', 'Wrong repository, branch, workflow, or event')
    control = env.get('GITHUB_SHA', '')
    require(re.fullmatch('[0-9a-f]{40}', control) and env.get('GITHUB_WORKFLOW_SHA') == control,
            'Workflow event and control SHA do not match')
    require(git('rev-parse', 'HEAD') == control, 'Checked-out control commit mismatch')
    control_tree = git('rev-parse', 'HEAD^{tree}')
    product = config['corrected_product_sha']
    lineage = git('rev-list', '--first-parent', '--max-count=' + str(MAX_CONTROL_COMMITS + 1), 'HEAD').splitlines()
    require(product in lineage and 1 <= lineage.index(product) <= MAX_CONTROL_COMMITS,
            'Exact product root absent from bounded control-only chain')
    controls = lineage[:lineage.index(product)]
    previous = git('show', product + ':scripts/retain_mac_evidence.py')
    require(previous.count('WORKFLOW_IDENTITIES = {\n') == 1, 'Unexpected historical Mac evidence source')
    admitted_mac = previous.replace('WORKFLOW_IDENTITIES = {\n', 'WORKFLOW_IDENTITIES = {\n' + MAC_IDENTITY, 1)
    previous_test = git('show', product + ':scripts/test_retain_mac_evidence.py')
    admitted_test = previous_test
    for old, new in MAC_IDENTITY_TEST_EDITS:
        require(admitted_test.count(old) == 1, 'Unexpected historical identity-count test')
        admitted_test = admitted_test.replace(old, new, 1)
    for commit in controls:
        parents = git('rev-list', '--parents', '-n', '1', commit).split()
        require(len(parents) == 2, 'Every control commit must have a sole parent; merges are rejected')
        transition = set(git('diff', '--name-only', '--no-renames', parents[1], commit, '--').splitlines())
        require(transition and transition <= OVERLAY_PATHS, 'A control transition changed product source or lacks an explicit control edit')
        require(git('show', commit + ':scripts/retain_mac_evidence.py') == admitted_mac,
                'Historical Mac evidence code changed beyond exact new-route admission')
        require(git('show', commit + ':scripts/test_retain_mac_evidence.py') == admitted_test,
                'Historical Mac evidence tests changed beyond exact new-route count')
        for path in OVERLAY_PATHS:
            require(git('ls-tree', commit, '--', path).startswith('100644 blob '), 'Unexpected control-file mode/type: ' + path)
    require(git('rev-parse', product + '^{tree}') == config['corrected_product_tree'], 'Corrected product tree mismatch')
    # All additions are ordinary non-executable source files. No app, project,
    # version, signing, legacy workflow or acceptance assertion may be changed.
    changed = set(git('diff', '--name-only', '--no-renames', product, 'HEAD', '--').splitlines())
    require(changed == OVERLAY_PATHS, 'Control commit must contain only the complete reviewed qualification overlay')
    for path in OVERLAY_PATHS:
        require(git('ls-tree', 'HEAD', '--', path).startswith('100644 blob '), 'Unexpected control-file mode/type: ' + path)
        if path not in ('scripts/retain_mac_evidence.py', 'scripts/test_retain_mac_evidence.py'):
            require(git('ls-tree', product, '--', path) == '', 'Qualification control path already existed in product source: ' + path)
    require(git('status', '--porcelain', '--untracked-files=normal') == '', 'Dirty tracked source or unexpected untracked files')
    row = select(config['selected_lane'])
    workflow = Path(WORKFLOW).read_text()
    require(workflow == render_selection(workflow, config), 'Baked native selection differs from config; run local prepare before publication')
    if env.get('GITHUB_JOB') == 'native-platform':
        expected = {'TOUCHCOLOR_JOB_PLATFORM': row['platform'], 'TOUCHCOLOR_JOB_LANE': row.get('lane', row['platform']),
                    'TOUCHCOLOR_JOB_MINUTES': str(row['minutes']), 'TOUCHCOLOR_EVIDENCE_LIMIT': str(row['evidence_bytes']),
                    'TOUCHCOLOR_VISION_CASE': row.get('vision_case', ''), 'TOUCHCOLOR_WATCH_PROFILE': row.get('watch_profile', ''),
                    'TOUCHCOLOR_TEXT_PHASE': row.get('text_phase', '')}
        require(all(env.get(key, '') == value for key, value in expected.items()), 'Native job differs from the admitted row')
    else:
        raise ValueError('Unexpected qualification job; only the selected native job is permitted')
    return {'corrected_product_sha': product, 'corrected_product_tree': config['corrected_product_tree'],
            'control_sha': control, 'control_tree': control_tree, 'control_commits': len(controls), 'row': row, 'deferred': DEFERRED,
            'native_execution': 'not established by admission'}


def main():
    require(sys.argv[1:] in (['admit'], ['prepare']), 'Only local prepare or in-job admission is supported')
    if sys.argv[1:] == ['prepare']:
        prepare()
        return
    receipt = admit()
    print(json.dumps(receipt, indent=2))
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as stream:
            stream.write('## Exact unsigned qualification scope\n\n')
            for key in ('corrected_product_sha', 'corrected_product_tree', 'control_sha', 'control_tree'):
                stream.write(key + ': ' + receipt[key] + '\n\n')
            stream.write('Selected row: ' + receipt['row'].get('lane', receipt['row']['platform']) + '\n\n')
            for value in DEFERRED.values():
                stream.write('- ' + value + '\n')


if __name__ == '__main__':
    main()
