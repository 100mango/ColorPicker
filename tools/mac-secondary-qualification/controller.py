"""CLOSED two-job Mac controller. One Session owns every selected native child."""
import sys
sys.dont_write_bytecode = True
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import argparse
import hashlib
import json
import os
import plistlib
import re
import stat
import subprocess
import tempfile
import time

import commands
from budget import Ledger, RESERVES, STARTUP, WORK
import io_boundary as io
import owned_mac_process as owned
import runtime_contract as runtime
import self_test
import source_guard as source


def require(value, message):
    if not value:
        raise ValueError(message)


class FinalizedNativeFailure(RuntimeError):
    cleanup_confirmed = True


class Controller:
    def __init__(self, lane, *, session=None, clock=time.monotonic, wall=time.time):
        self.lane, self.clock, self.wall = lane, clock, wall
        self.plan = commands.stages(lane)
        require(all(os.environ.get(k) == v for k, v in {'BOOTSTRAP_OUTCOME': 'success', 'COMPILE_OUTCOME': 'success', 'COMPILE_EXIT': '0'}.items()), 'Actual compiler bootstrap did not succeed')
        self.source = source.check(lane)
        self.expected = commands.validate()
        require(source.tools_manifest()['READY'] is True, 'CLOSED control cannot execute')
        self.start = float(os.environ['TOUCHCOLOR_JOB_STARTED_MONOTONIC'])
        self.epoch = float(os.environ['TOUCHCOLOR_JOB_STARTED_EPOCH'])
        require(self.epoch <= wall() and clock() - self.start >= 0, 'Invalid original job clock')
        self.ledger = Ledger(self.start, self.plan, epoch=self.epoch, clock=clock, wall=wall)
        self.session = session or owned.Session(owned.PublicMac(io.REPO / 'build/mac-owned-public.dylib'))
        self.results, self.records, self.memory_logs = {}, {}, {}
        self.failures = []
        self.host = None
        self.fixture = None
        io.mkdir(io.REPO / 'build/mac-control/commands')
        io.mkdir(io.REPO / 'build/evidence')
        self.write('build/job-budget.json', {'schema': 1, 'platform': 'mac', 'minutes': 40,
            'started_epoch': self.epoch, 'started_monotonic': self.start, 'lane': lane,
            'sha': os.environ['GITHUB_SHA'], 'run_id': os.environ['GITHUB_RUN_ID'],
            'reserves': RESERVES, 'startup_margin': STARTUP})

    def write(self, path, value, replace=False):
        io.write(io.REPO / path, io.encoded(value), replace=replace)

    def poison(self, error):
        # In-memory stop wins even when writing the failure marker itself fails.
        if self.session.fault is None:
            self.session.fault = error
        self.ledger.poisoned = True
        value = {'schema': 1, 'source_sha': os.environ.get('GITHUB_SHA'), 'run_id': os.environ.get('GITHUB_RUN_ID'),
                 'lane': self.lane, 'error': type(error).__name__, 'reason': str(error)[:512],
                 'cleanup_unconfirmed': getattr(error, 'cleanup_confirmed', False) is not True,
                 'owned': getattr(error, 'owned_receipt', None)}
        try:
            self.write('build/job-budget-cleanup-unconfirmed.json', value)
        except (OSError, ValueError):
            pass  # Admission remains poisoned; there is no native fallback.
        return value

    def failed(self, error):
        if not isinstance(error, FinalizedNativeFailure) or self.session.fault is not None:
            return self.poison(error)
        return {'error': type(error).__name__, 'reason': str(error)[:512], 'cleanup_unconfirmed': False,
                'native_failures': self.failures, 'owned': getattr(error, 'owned_receipt', None)}

    def execute(self, step, allocation):
        if step['action'] is not None:
            prior = io.DEADLINE
            io.DEADLINE = min(allocation['work_deadline'], self.ledger.phase_end('work'))
            self.local_deadline = io.DEADLINE
            try:
                self.local_fence()
                result = self.action(step['action'], allocation)
                self.ledger.check_local(allocation)
                return result
            finally:
                io.DEADLINE = prior
        if step['id'] == 'api-typecheck':
            self.validate_sdk()
        argv = list(step['argv'])
        for index, value in enumerate(argv):
            argv[index] = value.replace('$SDK_PLATFORM', self.results.get('sdk-platform', '').strip()).replace('$SDK_PATH', self.results.get('sdk-path', '').strip())
        role = step['role']
        cases = runtime.Cases(self.expected[role]) if role else None
        started_epoch = self.wall()
        observed = [bytearray(), bytearray()]
        def consume(index, raw):
            observed[index].extend(raw)
            if cases is not None:
                cases.consume(index, raw)
        try:
            self.ledger.recheck(allocation, step['cleanup'])
            result = self.session.run(argv, work_deadline=allocation['work_deadline'], cleanup_deadline=allocation['cleanup_deadline'],
                                      maximum_bytes=2_000_000, text=not bool(role),
                                      stderr=subprocess.STDOUT if role or step['id'] == 'api-typecheck' else subprocess.PIPE,
                                      consume=consume)
        except BaseException as error:
            raw = bytes(observed[0]) + bytes(observed[1])
            self.memory_logs[step['id']] = raw
            self.records[step['id']] = {**allocation, 'argv': argv, 'source_sha': os.environ['GITHUB_SHA'],
                'lane': self.lane, 'role': role, 'started_epoch': started_epoch, 'finished_epoch': self.wall(),
                'finished_monotonic': self.clock(), 'exit': None, 'error': type(error).__name__, 'reason': str(error)[:512],
                'owned': getattr(error, 'owned_receipt', None),
                'stdout': {'bytes': len(raw), 'sha256': io.digest(raw)},
                'stream_scope': 'Only callback-observed original bytes before failure; not a complete command stream'}
            raise
        finished_epoch, finished_mono = self.wall(), self.clock()
        stdout_raw = result.stdout if isinstance(result.stdout, bytes) else result.stdout.encode('utf-8')
        stderr_raw = result.stderr if isinstance(result.stderr, bytes) else (result.stderr or '').encode('utf-8')
        stdout_text = stdout_raw.decode('utf-8')
        record = {**allocation, 'argv': argv, 'source_sha': os.environ['GITHUB_SHA'], 'run_id': os.environ['GITHUB_RUN_ID'],
                  'run_attempt': os.environ['GITHUB_RUN_ATTEMPT'], 'lane': self.lane, 'role': role,
                  'started_epoch': started_epoch, 'finished_epoch': finished_epoch, 'finished_monotonic': finished_mono,
                  'exit': result.returncode, 'owned': result.owned_receipt,
                  'stdout': {'bytes': len(stdout_raw), 'sha256': io.digest(stdout_raw)},
                  'stderr': {'bytes': len(stderr_raw), 'sha256': io.digest(stderr_raw)}}
        if cases is not None:
            record['cases'] = cases.finish()
        self.memory_logs[step['id']] = stdout_raw + stderr_raw
        self.records[step['id']] = record
        self.results[step['id']] = stdout_text
        self.write('build/mac-control/commands/' + step['id'] + '.json', record)
        io.write(io.REPO / ('build/mac-control/' + step['id'] + '.log'),
                 stdout_raw + stderr_raw, maximum=2_000_000)
        # Original raw native log remains in the official job log as well as the
        # bounded runner-local capture; retained event lines are a declared subset.
        if role:
            print(stdout_text, end='', flush=True)
        if step['output']:
            io.write(io.REPO / step['output'], stdout_raw)
        if step['id'] == 'sandbox-entitlements-before':
            self.check_entitlements('build/mac-sandbox-entitlements.plist')
        if result.returncode or (cases is not None and record['cases']['complete'] is not True):
            failure = {'command': step['id'], 'exit': result.returncode, 'exact_case_complete': record.get('cases', {}).get('complete')}
            self.failures.append(failure)
            # The original sandbox script preserves a failed UI exit while still
            # doing signature/entitlement/fixture postchecks after safe cleanup.
            if step['id'] != 'sandbox':
                error = FinalizedNativeFailure('Required native stage failed: ' + step['id'])
                error.cleanup_confirmed = True
                raise error
        return result

    def action(self, name, allocation):
        if name == 'launcher-self-test':
            receipt = self_test.run(self.session, work_deadline=allocation['work_deadline'], cleanup_deadline=allocation['cleanup_deadline'])
            self.write('build/mac-control/launcher-self-test.json', receipt)
            return
        if name == 'source-host-contract':
            sha = os.environ['GITHUB_SHA']
            require(self.results['source-head'].strip() == sha, 'Actual HEAD mismatch')
            require(self.results['source-parent'].split() == [sha, source.BASE], 'Control must have sole actual84da71d parent')
            require(self.results['source-clean'] == '', 'Tracked source changed')
            require(sorted(self.results['source-changes'].splitlines()) == self.source['added_paths'], 'Unexpected changed source paths')
            require(re.fullmatch('[0-9a-f]{40}', self.results['source-tree'].strip()), 'Missing actual control tree')
            host = {'version': self.results['host-version'].strip(), 'build': self.results['host-build'].strip(),
                    'architecture': self.results['host-architecture'].strip(), 'source_sha': sha,
                    'product_sha': source.PRODUCT, 'control_tree': self.results['source-tree'].strip(),
                    'run_id': os.environ['GITHUB_RUN_ID'], 'run_attempt': os.environ['GITHUB_RUN_ATTEMPT'],
                    'observed_at': self.wall(), 'os_equivalence_claim': False}
            print('MAC_ACTUAL_HOST', json.dumps(host, sort_keys=True), flush=True)
            require((host['version'], host['build']) in runtime.PAIRS and host['architecture'] == 'arm64', 'Unapproved exact host pair')
            require(self.results['xcode-version'].splitlines() == ['Xcode 27.0', 'Build version 27A266a'], 'Wrong actual Xcode build')
            project = json.loads(self.results['scheme-list'])['project']
            require({'TouchColorMac', 'TouchColorMacSandbox'} <= set(project['schemes']) and
                    {'TouchColorMac', 'TouchColorMacTests', 'TouchColorMacUITests'} <= set(project['targets']), 'Actual scheme/target inventory differs')
            source.protected()
            destinations = re.findall(r'\{\s*platform:macOS,\s*arch:arm64,\s*id:([^,}]+),[^}]*\}', self.results['actual-destination'])
            require(len(set(destinations)) == 1, 'Missing or ambiguous actual arm64 Mac destination')
            host['destination_id'] = destinations[0].strip()
            self.host = host
            self.write('build/mac-control/host.json', host)
            io.mkdir(io.REPO / 'build/accessibility-api')
            io.write(io.REPO / 'build/accessibility-api/AuditProbe.swift',
                     b'import XCTest\n@MainActor func audit(_ app: XCUIApplication) throws { try app.performAccessibilityAudit(for: .all) { issue in print(issue.compactDescription); return false } }\n')
            return
        if name == 'api-record':
            self.validate_sdk()
            self.write('build/accessibility-api/results.json', [{'sdk': 'macosx', 'exit': self.records['api-typecheck']['exit'],
                'diagnostic': self.results['api-typecheck'][-10000:], 'scope': 'typecheck only; not a runtime audit'}])
            return
        if name in ('normal-fixture', 'sandbox-fixture'):
            self.make_fixture('mac-tests' if name == 'normal-fixture' else 'mac-sandbox')
            if name == 'sandbox-fixture':
                shipping = plistlib.loads(io.read(io.REPO / 'TouchColorMac/TouchColorMac.entitlements', 65536))
                require(shipping == self.entitlements(False), 'Shipping sandbox contract changed')
                shipping['com.apple.security.get-task-allow'] = True
                io.write(io.REPO / 'build/mac-sandbox-minimal.entitlements', plistlib.dumps(shipping))
            return
        if name == 'normal-build-record':
            root = io.REPO / 'build/mac-tests/Build/Products'
            files = list(root.glob('*.xctestrun'))
            require(len(files) == 1, 'Expected one actual normal xctestrun')
            value = plistlib.loads(io.read(files[0], 2_000_000))
            expected = {'TouchColorMacTests.xctest', 'TouchColorMacUITests.xctest'}
            references = []
            pending = [value]
            nodes = 0
            while pending:
                self.local_fence()
                node = pending.pop(); nodes += 1
                require(nodes <= 4096, 'Unbounded actual xctestrun structure')
                if isinstance(node, dict):
                    if 'TestBundlePath' in node:
                        require(type(node['TestBundlePath']) is str, 'Invalid actual test bundle path')
                        references.append(node['TestBundlePath'])
                    pending.extend(node.values())
                elif isinstance(node, list):
                    pending.extend(node)
            require(len(references) == 2 and {Path(x).name for x in references} == expected, 'Full normal build omitted or added a test bundle')
            bundles = []
            inspected = 0
            for folder, directories, unused in os.walk(root, followlinks=False):
                self.local_fence()
                inspected += len(directories) + len(unused) + 1
                require(inspected <= 8192, 'Unbounded owned build product inventory')
                for directory in list(directories):
                    path = Path(folder) / directory
                    if path.is_symlink():
                        require(not path.name.endswith('.xctest'), 'Aliased actual test bundle')
                        directories.remove(directory)
                        continue  # Never traverse normal framework symlink layouts.
                    if path.name.endswith('.xctest'):
                        bundles.append(path.relative_to(root).as_posix())
                        directories.remove(directory)
            require(len(bundles) == 2 and {Path(x).name for x in bundles} == expected, 'Actual normal test bundles missing/ambiguous')
            self.write('build/mac-control/normal-built-test-plan.json', {'path': str(files[0].relative_to(io.REPO)),
                'sha256': io.digest(io.read(files[0], 2_000_000)), 'requires_hosted_and_ui': True,
                'test_bundle_references': references, 'actual_owned_test_bundles': bundles})
            return
        if name == 'normal-fixture-after':
            self.check_fixture(sandbox=False)
            return
        if name == 'release-validate':
            self.validate_release()
            return
        if name == 'sandbox-boundary-after':
            before = self.check_entitlements('build/mac-sandbox-entitlements.plist')
            after = self.check_entitlements('build/mac-sandbox-post-entitlements.plist')
            require(before == after, 'Runtime changed the exact signature entitlements')
            self.check_fixture()
            return
        raise ValueError('Unregistered pure action: ' + name)

    def validate_sdk(self):
        developer = Path(os.environ['DEVELOPER_DIR']).resolve(strict=True)
        paths = {key: Path(self.results[key].strip()).resolve(strict=True) for key in ('sdk-platform', 'sdk-path')}
        for path in paths.values():
            path.relative_to(developer)
            require(path.is_dir() and path.stat().st_uid == developer.stat().st_uid, 'Foreign/non-directory macOS SDK path')
        require(paths['sdk-platform'].name == 'MacOSX.platform', 'Wrong SDK platform')
        paths['sdk-path'].relative_to(paths['sdk-platform'] / 'Developer/SDKs')
        require(re.fullmatch(r'MacOSX(?:27(?:\.0)?)?\.sdk', paths['sdk-path'].name) is not None, 'Unapproved macOS SDK version path')

    @staticmethod
    def entitlements(debug=True):
        values = {'com.apple.security.app-sandbox': True, 'com.apple.security.files.user-selected.read-write': True,
                  'com.apple.security.device.camera': True}
        if debug:
            values['com.apple.security.get-task-allow'] = True
        return values

    def check_entitlements(self, relative):
        value = plistlib.loads(io.read(io.REPO / relative, 65536))
        require(value == self.entitlements() and all(type(x) is bool for x in value.values()), 'Exact disposable Debug entitlements differ')
        return value

    def local_fence(self):
        require(self.clock() < min(self.local_deadline, self.ledger.phase_end('work')), 'Pure action exhausted its original allocation')

    def make_fixture(self, directory):
        self.local_fence()
        temp = Path(os.environ['RUNNER_TEMP']).resolve(strict=True)
        require(temp.is_dir() and temp.stat().st_uid == os.geteuid(), 'Foreign runner temporary directory')
        parent = io.snapshot._open_absolute(temp, self.local_deadline, self.clock)
        folder_fd = None
        try:
            self.local_fence()
            io.mutation_fence(parent, self.local_deadline)
            name = 'TouchColor-boundary-' + os.urandom(12).hex()
            self.local_fence()
            os.mkdir(name, 0o700, dir_fd=parent)
            folder = temp / name
            folder_fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            folder_identity = os.fstat(folder_fd)
            require(folder_identity.st_uid == os.geteuid() and stat.S_IMODE(folder_identity.st_mode) == 0o700, 'Wrong fixture directory owner/mode')
            io.snapshot._anchor(folder_fd, folder, self.local_deadline, self.clock)
            self.local_fence()
            io.mutation_fence(folder_fd, self.local_deadline)
            fd = os.open('unselected.txt', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=folder_fd)
            try:
                self.local_fence()
                witness = b'TouchColor synthetic read witness'
                require(os.write(fd, witness) == len(witness), 'Short fixture witness write')
                identity = os.fstat(fd)
            finally:
                os.close(fd)
            path = folder / 'unselected.txt'
            require(io.reader._file_receipt(folder_fd, path.name, os.geteuid(), 1024, deadline=self.local_deadline) == witness, 'Host read witness failed')
            self.local_fence()
            fd = os.open(path.name, os.O_WRONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=folder_fd)
            try:
                reopened = os.fstat(fd)
                require((reopened.st_dev, reopened.st_ino, reopened.st_uid, reopened.st_nlink) ==
                        (identity.st_dev, identity.st_ino, os.geteuid(), 1), 'Existing fixture changed before host write control')
                payload = b'TouchColor synthetic host write control'
                self.local_fence()
                require(os.write(fd, payload) == len(payload), 'Short existing-file host write control')
                self.local_fence()
                os.ftruncate(fd, len(payload))
            finally:
                os.close(fd)
            require(io.reader._file_receipt(folder_fd, path.name, os.geteuid(), 1024, deadline=self.local_deadline) == payload, 'Existing-file host write control failed')
            io.snapshot._anchor(folder_fd, folder, self.local_deadline, self.clock)
            self.fixture = {'file': str(path), 'uid': os.geteuid(), 'readControl': True, 'writeControl': True,
                            'device': identity.st_dev, 'inode': identity.st_ino, 'directory_fd': folder_fd,
                            'directory_device': folder_identity.st_dev, 'directory_inode': folder_identity.st_ino}
            folder_fd = None  # Hold the non-inheritable directory through actual UI.
            self.write('build/' + directory + '/probe-info.json', {key: self.fixture[key] for key in ('file', 'uid', 'readControl', 'writeControl')})
        finally:
            if folder_fd is not None:
                os.close(folder_fd)
            os.close(parent)

    def check_fixture(self, *, sandbox=True):
        require(self.fixture is not None, 'Missing exact sandbox fixture')
        path = Path(self.fixture['file'])
        directory = self.fixture['directory_fd']
        self.local_fence()
        io.snapshot._anchor(directory, path.parent, self.local_deadline, self.clock)
        info = os.stat(path.name, dir_fd=directory, follow_symlinks=False)
        require((info.st_dev, info.st_ino, info.st_uid, info.st_nlink) ==
                (self.fixture['device'], self.fixture['inode'], self.fixture['uid'], 1), 'Fixture identity changed')
        require(stat.S_IMODE(info.st_mode) == 0o600 and stat.S_IMODE(os.fstat(directory).st_mode) == 0o700, 'Fixture permissions changed')
        if sandbox:
            require(io.reader._file_receipt(directory, path.name, os.geteuid(), 1024, deadline=self.local_deadline) ==
                    b'TouchColor synthetic host write control', 'Sandbox changed unselected same-user control')
        self.write('build/mac-control/' + ('sandbox' if sandbox else 'normal') + '-host-boundary.json',
                   {'complete': True, 'uid': info.st_uid, 'same_user_unselected_file_unchanged': sandbox,
                    'path_sha256': hashlib.sha256(str(path).encode()).hexdigest()})
        self.local_fence()
        io.snapshot._anchor(directory, path.parent, self.local_deadline, self.clock)
        io.mutation_fence(directory, self.local_deadline)
        os.unlink(path.name, dir_fd=directory)
        parent = io.snapshot._open_absolute(path.parent.parent, self.local_deadline, self.clock)
        try:
            actual = os.stat(path.parent.name, dir_fd=parent, follow_symlinks=False)
            require((actual.st_dev, actual.st_ino) == (self.fixture['directory_device'], self.fixture['directory_inode']), 'Fixture folder identity changed')
            self.local_fence()
            io.mutation_fence(parent, self.local_deadline)
            os.rmdir(path.parent.name, dir_fd=parent)
        finally:
            os.close(parent)
            os.close(directory)
            self.fixture = None

    def validate_release(self):
        # Reuse the exact original pure verifier; no subprocess route is imported.
        records = io.json_read(io.REPO / 'build/mac-release-settings.json', 1_000_000)
        settings = [row.get('buildSettings') for row in records if row.get('target') == 'TouchColorMac']
        require(len(settings) == 1 and settings[0].get('SRCROOT') == str(io.REPO) and
                settings[0].get('TARGET_BUILD_DIR') == str(io.REPO / 'build/mac-arm64/Build/Products/Release'),
                'Release settings refer to a different source or build product')
        # Preserve original verifier logic while binding its reads to the same bounded descriptors.
        text = io.bootstrap_source('verify_mac_release_settings').decode()
        old = 'records = json.loads(Path(settings_path).read_text())'
        require(text.count(old) == 1, 'Original release verifier shape changed')
        text = text.replace(old, 'records = json.loads(safe_read(settings_path, 1_000_000))')
        import types
        module = types.ModuleType('exact_release_verifier')
        module.safe_read = io.read
        exec(compile(text, 'exact_release_verifier', 'exec'), module.__dict__)
        module.plist = lambda path, maximum_bytes: plistlib.loads(io.read(path, maximum_bytes))
        self.local_fence()
        report = module.verify(io.REPO / 'build/mac-release-settings.json')
        require(report['app'] == str(io.REPO / 'build/mac-arm64/Build/Products/Release/TouchColor.app'), 'Release report app differs')
        app = Path(report['app'])
        info = plistlib.loads(io.read(app / 'Contents/Info.plist', 1_000_000))
        require(info.get('CFBundleName') == 'TouchColor' and bool(info.get('NSCameraUsageDescription')), 'Original name/Camera metadata missing')
        manifest = plistlib.loads(io.read(app / 'Contents/Resources/PrivacyInfo.xcprivacy', 65536))
        expected = plistlib.loads(io.read(io.REPO / 'TouchColorMac/PrivacyInfo.xcprivacy', 65536))
        require(manifest == expected, 'Built privacy manifest differs from original selected contract')
        accessed = manifest.get('NSPrivacyAccessedAPITypes')
        require(type(accessed) is list and len(accessed) == 2, 'Wrong privacy accessed API inventory')
        api_reasons = {item['NSPrivacyAccessedAPIType']: set(item['NSPrivacyAccessedAPITypeReasons']) for item in accessed}
        require(api_reasons == {'NSPrivacyAccessedAPICategoryUserDefaults': {'CA92.1'},
                               'NSPrivacyAccessedAPICategoryFileTimestamp': {'C617.1', '3B52.1'}} and
                manifest.get('NSPrivacyTracking') is False and manifest.get('NSPrivacyCollectedDataTypes') == [] and
                manifest.get('NSPrivacyTrackingDomains') == [], 'Original privacy declarations changed')
        require('arm64' in self.results['release-lipo'] and 'LC_BUILD_VERSION' in self.results['release-build-version'], 'Release architecture/build version inspection missing')
        require(not re.search(r'--ui-test-|TOUCHCOLOR_TEST_DEFAULTS|TOUCHCOLOR_SANDBOX_PROBE_FILE|TOUCHCOLOR_NATIVE_MODAL_PROBE|TOUCHCOLOR_MAC_LIFECYCLE|MAC_PASSIVE_LIFECYCLE|com.mango.touchColor.MacLifecycle|debug.sandbox.proof|TouchColor-fixture-', self.results['release-strings']), 'Test seam leaked into Release')
        self.write('build/mac-control/release-validation.json', report)

    def work(self):
        for index, stage in enumerate(self.plan):
            self.ledger.enter(index)
            for step in stage['commands']:
                allocation = self.ledger.admit(step)
                self.execute(step, allocation)
            self.ledger.finish_stage()
        return not self.failures


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('lane', choices=('normal', 'sandbox'))
    args = parser.parse_args()
    controller = None
    failure = None
    try:
        controller = Controller(args.lane)
        controller.work()
    except BaseException as error:
        failure = controller.failed(error) if controller is not None else {'error': type(error).__name__, 'reason': str(error)[:512]}
    # Evidence binding is a separate module using this same Session. No helper
    # process or native exporter is allowed after a poisoned controller.
    if controller is not None:
        from evidence import finish
        complete = finish(controller, failure)
    else:
        complete = False
        io.mkdir(io.REPO / 'build/evidence')
        io.write(io.REPO / 'build/evidence/mac-row-result.json', io.encoded({'complete': False, 'failure': failure}), maximum=8192)
    return 0 if complete else 1


if __name__ == '__main__':
    raise SystemExit(main())
