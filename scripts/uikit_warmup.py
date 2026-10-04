"""One 600-second UIKit preparation clock, with owned-command containment."""
import time

STARTED = time.monotonic()  # Includes imports, selection, setup and fixture checks.

import datetime
import json
import os
from pathlib import Path
import subprocess
import sys

from atomic_json import write_json
from bounded_process import run_captured
from job_budget import enabled_budget, fail_record

FAMILIES = {'iPhoneCompact', 'iPhoneLarge', 'iPadLarge', 'iPadMini'}
SECONDS = 600
CLEANUP = 20  # bounded_process.stop_group has two ten-second signal phases.


class WarmupFailed(RuntimeError):
    pass


class Warmup:
    def __init__(self, family, *, started, clock=time.monotonic, runner=run_captured,
                 budget=None, sleep=time.sleep):
        if family not in FAMILIES:
            raise ValueError('Unknown simulator family')
        self.family, self.clock, self.runner = family, clock, runner
        self.budget, self.sleep = budget, sleep
        self.deadline = started + SECONDS
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
        self.command(['xcrun', 'simctl', 'install', device,
                      'build/simulator/Build/Products/Debug-iphonesimulator/TouchColor.app'], 90)
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


def main():
    controller = None
    try:
        if len(sys.argv) == 3 and sys.argv[2] == 'report':
            return report_inventory(sys.argv[1])
        budget = enabled_budget()
        controller = Warmup(sys.argv[1], started=STARTED, budget=budget)
        controller.prepare(sys.argv[2])
        return 0
    except Exception as error:
        if os.environ.get('TOUCHCOLOR_BUDGET_PHASE') in ('work', 'cleanup', 'evidence'):
            fail_record('UIKit preparation failed: ' + str(error),
                        phase=os.environ['TOUCHCOLOR_BUDGET_PHASE'],
                        cleanup_unconfirmed=bool(controller and (controller.pending.exists() or controller.pending.is_symlink())))
        print('BLOCKED: ' + str(error), file=sys.stderr, flush=True)
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
