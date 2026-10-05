"""Absolute UIKit preparation/seed clocks, with owned-command containment."""
import time

STARTED = time.monotonic()  # Includes imports, selection, setup and fixture checks.

import contextlib
import datetime
import json
import os
from pathlib import Path
import signal
import struct
import subprocess
import sys
import tempfile
import zlib

from atomic_json import write_json
from bounded_process import run_captured
from job_budget import enabled_budget, fail_record
from uikit_runtime_diagnostics import validate_identity

FAMILIES = {'iPhoneCompact', 'iPhoneLarge', 'iPadLarge', 'iPadMini'}
SECONDS = 600
CLEANUP = 20  # bounded_process.stop_group has two ten-second signal phases.


class WarmupFailed(RuntimeError):
    pass


class Warmup:
    def __init__(self, family, *, started, clock=time.monotonic, runner=run_captured,
                 budget=None, sleep=time.sleep, seconds=SECONDS):
        if family not in FAMILIES:
            raise ValueError('Unknown simulator family')
        self.family, self.clock, self.runner = family, clock, runner
        self.budget, self.sleep = budget, sleep
        self.deadline = started + seconds
        self.build = Path('build')
        if self.build.is_symlink():
            raise WarmupFailed('Unsafe build root')
        self.build.mkdir(exist_ok=True)
        self.pending = self.build / (family + '-runtime-command-uncertain')
        if self.pending.exists() or self.pending.is_symlink():
            raise WarmupFailed('An earlier owned command has no confirmed timely exit')

    def remaining(self):
        remaining = self.deadline - self.clock()
        if self.budget is not None:
            remaining = min(remaining, self.budget.remaining())
        return remaining

    def require_time(self):
        if self.remaining() <= CLEANUP:
            raise WarmupFailed('UIKit preparation exhausted its unchanged deadline')

    def command(self, arguments, seconds, *, optional=False, simulator=True):
        self.require_time()
        granted = min(seconds, self.remaining() - CLEANUP)
        if self.budget is not None:
            granted = self.budget.admit('UIKit preparation: ' + ' '.join(arguments[:3]),
                                       granted, minimum=min(1, granted), cleanup=CLEANUP)
        # Exclusive creation also rejects a marker added by another controller.
        with self.pending.open('x') as marker:
            marker.write('Owned preparation command has no confirmed timely exit.\n')
        began = self.clock()
        print(datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'UIKit preparation:', ' '.join(arguments[:3]), 'allowance=%.3fs' % granted, flush=True)
        try:
            result = self.runner(arguments, timeout=granted)
        except subprocess.TimeoutExpired as error:
            print('UIKit preparation timeout: host_process_cleanup_confirmed=%s; simulator_command_completion=%s; simulator_shutdown=not_confirmed' %
                  (getattr(error, 'cleanup_confirmed', False), 'unconfirmed' if simulator else 'not_requested'), flush=True)
            # Reaping simctl does not prove its daemon-side request stopped.
            # Only the optional host-only inventory can safely be omitted.
            if (optional and not simulator and getattr(error, 'cleanup_confirmed', False)
                    and self.clock() - began <= granted + CLEANUP and self.remaining() > 0):
                self.pending.unlink()
                print('Optional host inventory exceeded its bound; owned group exit confirmed', flush=True)
                return None
            raise WarmupFailed('Preparation command timed out; later simulator actions are blocked') from error
        # A native lookup can return successfully after its nominal timeout.
        # Never turn that into a successful warmup or start the next command.
        elapsed = self.clock() - began
        if elapsed > granted or self.remaining() <= 0:
            raise WarmupFailed('Preparation command returned after its admitted deadline: elapsed=%.3fs allowance=%.3fs' % (elapsed, granted))
        self.pending.unlink()
        print('UIKit preparation exit:', result.returncode, 'elapsed=%.3fs' % elapsed, flush=True)
        if result.returncode and not optional:
            raise WarmupFailed('Preparation command failed with exit ' + str(result.returncode))
        if optional and not simulator and result.stdout:
            print(result.stdout, end='' if result.stdout.endswith('\n') else '\n', flush=True)
        return result.stdout

    def select(self):
        data = json.loads(self.command(['xcrun', 'simctl', 'list', 'devices', 'available', '-j'], 30))['devices']
        runtimes = [key for key in data if key.endswith('.iOS-27-0')]
        if not runtimes:
            raise WarmupFailed('Stable iOS 27.0 simulator runtime is unavailable')
        runtime = runtimes[0]
        if self.family == 'iPhoneCompact':
            types = json.loads(self.command(['xcrun', 'simctl', 'list', 'devicetypes', '-j'], 30))['devicetypes']
            device_type = next((t for t in types if t['name'] == 'iPhone SE (3rd generation)'), None)
            if device_type is None:
                raise WarmupFailed('Required iPhone SE (3rd generation) device type is unavailable')
            name = 'TouchColor Compact SE3'
        elif self.family == 'iPadMini':
            name = 'iPad mini (A17 Pro)'
        elif self.family == 'iPhoneLarge':
            name = 'iPhone 18 Pro Max'
        else:
            name = None
        candidates = [d for d in data[runtime] if d.get('isAvailable') and
                      (d['name'] == name if name else d['name'].startswith('iPad Pro 13-inch'))]
        if not candidates and self.family == 'iPhoneCompact':
            identifier = self.command(['xcrun', 'simctl', 'create', name, device_type['identifier'], runtime], 60).strip()
            candidates = [{'udid': identifier, 'name': name}]
        if not candidates:
            raise WarmupFailed('Missing required ' + (name or 'native 13-inch iPad') + ' simulator')
        selected = candidates[0]
        self.require_time()
        write_json(self.build / (self.family + '-simulator.json'),
                   {'family': self.family, 'udid': selected['udid'], 'runtime': runtime, 'started': time.time()})
        print('Selected ' + selected['name'] + ' ' + selected['udid'], flush=True)
        return selected['udid']

    def owned_device(self):
        """Read the existing binding before inventory; never select/rebind here."""
        self.require_time()
        self.identity_path = self.build / (self.family + '-simulator.json')
        if (self.identity_path.is_symlink() or not self.identity_path.is_file()
                or self.identity_path.stat().st_size > 8192):
            raise WarmupFailed('Missing or unsafe recorded owned device binding')
        self.identity_bytes = self.identity_path.read_bytes()
        self.identity = validate_identity(json.loads(self.identity_bytes), self.family)
        devices = json.loads(self.command(
            ['xcrun', 'simctl', 'list', 'devices', 'available', '-j'], 30))['devices']
        names = {'iPhoneCompact': 'TouchColor Compact SE3', 'iPhoneLarge': 'iPhone 18 Pro Max',
                 'iPadMini': 'iPad mini (A17 Pro)'}
        matches = [device for device in devices.get(self.identity['runtime'], [])
                   if device.get('udid') == self.identity['udid'] and device.get('isAvailable')]
        if len(matches) != 1 or not (matches[0]['name'].startswith('iPad Pro 13-inch')
                if self.family == 'iPadLarge' else matches[0]['name'] == names[self.family]):
            raise WarmupFailed('Inventory differs from the recorded owned device')
        self.require_identity()
        print('Selected recorded owned device ' + self.identity['udid'], flush=True)
        return self.identity['udid']

    def require_identity(self):
        self.require_time()
        if self.identity_path.is_symlink() or self.identity_path.read_bytes() != self.identity_bytes:
            raise WarmupFailed('Recorded owned device binding changed')

    def seed(self, device):
        self.require_identity()
        if device != self.identity['udid']:
            raise WarmupFailed('Seed target differs from the recorded owned device')
        seeded = self.build / (self.family + '-fixture-seeded')
        if seeded.is_symlink():
            raise WarmupFailed('Unsafe photo seed marker')
        if seeded.exists():
            if not seeded.is_file() or seeded.stat().st_size > 8192 or json.loads(seeded.read_text()) != self.identity:
                raise WarmupFailed('Photo seed marker differs from the recorded owned device')
            print('Synthetic photo already seeded for the recorded owned device', flush=True)
            return
        # Keep the original asymmetric six-color fixture, in this invocation's
        # private directory. A TMPDIR alias must not create shared global files.
        with tempfile.TemporaryDirectory(prefix=self.family + '-photo-', dir=self.build) as folder:
            path = Path(folder) / 'touchcolor-asymmetric.png'
            width, height = 300, 200
            def chunk(name, data):
                return (struct.pack('>I', len(data)) + name + data
                        + struct.pack('>I', zlib.crc32(name + data) & 0xffffffff))
            palette = [bytes(color) for color in
                       [(255, 0, 0), (0, 255, 0), (0, 0, 255), (0, 255, 255), (255, 0, 255), (255, 255, 0)]]
            rows = b''.join(b'\0' + b''.join(palette[(y // 100) * 3 + x // 100]
                                             for x in range(width)) for y in range(height))
            path.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
                             + chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b''))
            self.require_identity()
            self.command(['xcrun', 'simctl', 'addmedia', device, str(path)], SECONDS)
            self.require_identity()
            # Only a confirmed timely, zero addmedia exit can publish success.
            write_json(seeded, self.identity)
            self.require_time()
        print('Synthetic photo seed complete', flush=True)

    def shutdown(self, device):
        self.require_identity()
        if device != self.identity['udid']:
            raise WarmupFailed('Shutdown target differs from the recorded owned device')
        # A timely nonzero shutdown (already stopped) retains legacy behavior;
        # timeout, interruption and late exit always retain the stop latch.
        self.command(['xcrun', 'simctl', 'shutdown', device], 90, optional=True)

    def fixture(self, container):
        path = Path(container) / 'Documents/TouchColor-Ordered-Colors.json'
        deadline = min(self.clock() + 10, self.deadline - CLEANUP)
        while not path.is_file() and self.clock() < deadline:
            self.require_time()
            self.sleep(min(0.1, max(0, deadline - self.clock())))
        self.require_time()
        if self.clock() > deadline or not path.is_file():
            raise WarmupFailed('Synthetic Files fixture did not become ready within its deadline')
        if json.loads(path.read_text()) != ['#445566', '#445566', '#AABBCC']:
            raise WarmupFailed('Synthetic Files fixture contents differ')
        if len(list(path.parent.iterdir())) != 1:
            raise WarmupFailed('Only the deterministic JSON fixture may be exposed')
        self.require_time()
        print('Synthetic Files fixture is ready', flush=True)

    def prepare(self, suite):
        if suite not in ('prepare', 'prepare-unit'):
            raise ValueError('Unknown preparation suite')
        device = self.select()
        # f977 Large iPad's successful cold boot took ~125s before bootstatus
        # reported it already booted. Keep that observed path within the cap.
        self.command(['xcrun', 'simctl', 'boot', device], 180, optional=True)
        self.command(['xcrun', 'simctl', 'bootstatus', device, '-b'], 240)
        # Successful 0eda installs took 276s/208s on the Large profiles,
        # 179s on Mini and 89.204s by outer log timestamps on Compact.
        # Compact's whole-second markers span 90s, not proof of exceeding it.
        # This command still receives only the 600s remainder minus cleanup.
        install_seconds = 300  # self.family is one of the four closed, validated profiles.
        self.command(['xcrun', 'simctl', 'install', device,
                      'build/simulator/Build/Products/Debug-iphonesimulator/TouchColor.app'], install_seconds)
        self.command(['xcrun', 'simctl', 'launch', '--terminate-running-process', device, 'com.mango.touchColor'], 60)
        self.command(['xcrun', 'simctl', 'terminate', device, 'com.mango.touchColor'], 30)
        if suite == 'prepare-unit':
            self.require_time()
            print('Unit-only preparation complete; no Files fixture is used by TouchColorTests', flush=True)
            return
        self.command(['xcrun', 'simctl', 'install', device,
                      'build/palette-fixtures/Build/Products/Debug-iphonesimulator/PaletteFixtures.app'], 90)
        self.command(['xcrun', 'simctl', 'launch', '--terminate-running-process', device,
                      'com.mango.touchColor.tests.paletteFixtures'], 60)
        container = self.command(['xcrun', 'simctl', 'get_app_container', device,
                                  'com.mango.touchColor.tests.paletteFixtures', 'data'], 30).strip()
        self.fixture(container)
        self.command(['xcrun', 'simctl', 'terminate', device, 'com.mango.touchColor.tests.paletteFixtures'], 30)
        self.command(['xcrun', 'simctl', 'spawn', device, 'launchctl', 'print', 'system'], 20, optional=True)
        self.command(['xcodebuild', '-project', 'TouchColor.xcodeproj', '-scheme', 'TouchColor', '-showdestinations'],
                     30, optional=True, simulator=False)
        self.require_time()
        print('Simulator preparation complete', flush=True)


def report_inventory(family, *, runner=run_captured, clock=time.monotonic):
    """Reporting cannot bypass the same stop latch used by simulator cleanup."""
    value = {'family': family, 'inventory': 'not_started',
             'host_process_cleanup_confirmed': None, 'simulator_shutdown': 'not_confirmed'}
    pending = None
    try:
        if family not in FAMILIES:
            raise ValueError('Unknown simulator family')
        build = Path('build')
        if build.is_symlink():
            raise ValueError('Unsafe build root')
        build.mkdir(exist_ok=True)
        pending = build / (family + '-runtime-command-uncertain')
        if pending.exists() or pending.is_symlink():
            value['inventory'] = 'blocked_prior_uncertainty'
            return 3
        with pending.open('x') as marker:
            marker.write('Owned diagnostic command has no confirmed timely exit.\n')
        began = clock()
        result = runner(['xcrun', 'simctl', 'list', 'devices'], timeout=3)
        value['host_process_cleanup_confirmed'] = True  # run_captured confirmed its entire owned group.
        value['elapsed_seconds'] = round(clock() - began, 3)
        if clock() - began > 3:
            value['inventory'] = 'failed_late_exit'
            return 3
        pending.unlink()
        value['exit_code'] = result.returncode
        value['inventory'] = 'collected' if result.returncode == 0 else 'failed'
        if result.stdout:
            print(result.stdout, end='' if result.stdout.endswith('\n') else '\n', flush=True)
        return 0 if result.returncode == 0 else 3
    except Exception as error:
        value['inventory'] = 'failed_unconfirmed' if pending is not None and pending.exists() else 'blocked'
        value['error_type'] = type(error).__name__
        value['host_process_cleanup_confirmed'] = getattr(error, 'cleanup_confirmed', None)
        return 3
    finally:
        print('UIKIT_REPORT_DIAGNOSTICS:' + json.dumps(value, sort_keys=True), flush=True)


def interrupted(signum, frame):
    # Raise through run_captured so it can finitely reap its owned process group.
    # Repeated termination signals cannot interrupt that cleanup reserve.
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    raise WarmupFailed('UIKit owned command interrupted by signal ' + str(signum))


def main():
    controller = None
    try:
        if len(sys.argv) == 3 and sys.argv[2] == 'report':
            return report_inventory(sys.argv[1])
        suite = sys.argv[2]
        if suite not in ('prepare', 'prepare-unit', 'seed', 'shutdown',
                         'TouchColorTests', 'TouchColorUITests', 'AccessibilityAudits'):
            raise ValueError('Unknown simulator suite')
        budget = enabled_budget()
        controller = Warmup(sys.argv[1], started=STARTED, budget=budget,
                            seconds=120 if suite == 'shutdown' else SECONDS)
        if suite in ('prepare', 'prepare-unit'):
            controller.prepare(suite)
        else:
            # Shell substitution receives only the verified UUID; progress stays
            # visible in stderr, including the last admitted command on timeout.
            with contextlib.redirect_stdout(sys.stderr):
                device = controller.owned_device()
                if suite in ('seed', 'TouchColorUITests', 'AccessibilityAudits'):
                    controller.seed(device)
                elif suite == 'shutdown':
                    controller.shutdown(device)
                controller.require_identity()
            if suite not in ('seed', 'shutdown'):
                print(device, flush=True)
        return 0
    except Exception as error:
        if os.environ.get('TOUCHCOLOR_BUDGET_PHASE') in ('work', 'cleanup', 'evidence'):
            fail_record('UIKit preparation failed: ' + str(error),
                        phase=os.environ['TOUCHCOLOR_BUDGET_PHASE'],
                        cleanup_unconfirmed=bool(controller and (controller.pending.exists() or controller.pending.is_symlink())))
        print('BLOCKED: ' + str(error), file=sys.stderr, flush=True)
        return 3


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    raise SystemExit(main())
