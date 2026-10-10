"""Two exact phase ledgers layered over the unchanged original job clock."""
import math
import time

STARTUP = 30
RESERVES = {'cleanup': 130, 'evidence': 180, 'validation': 60, 'upload': 60, 'overhead': 20}
WORK = 40 * 60 - STARTUP - sum(RESERVES.values())


class Ledger:
    def __init__(self, start, plan, *, epoch=None, clock=time.monotonic, wall=time.time):
        if type(start) not in (int, float) or not math.isfinite(start) or start > clock():
            raise ValueError('Invalid original monotonic job start')
        self.start, self.plan, self.clock, self.wall = start, plan, clock, wall
        self.epoch = wall() - (clock() - start) if epoch is None else epoch
        if type(self.epoch) not in (int, float) or not math.isfinite(self.epoch) or self.epoch > wall() + 2:
            raise ValueError('Invalid original wall-clock start')
        # Same original JobBudget formula, with a sticky minimum on refresh:
        # clock rollback never extends; a forward jump can only shorten.
        self.hard_deadline = start + 40 * 60 - STARTUP
        self.refresh()
        self.evidence_end = None
        self.stage_index = -1
        self.command_index = 0
        self.deadline = start
        self.events = []
        self.poisoned = False

    def refresh(self):
        wall_remaining = self.epoch + 40 * 60 - STARTUP - self.wall()
        self.hard_deadline = min(self.hard_deadline, self.clock() + max(0, wall_remaining))
        self.work_end = self.hard_deadline - sum(RESERVES.values())
        return self.hard_deadline

    def phase_end(self, phase):
        self.refresh()
        tails = {'work': sum(RESERVES.values()),
                 'evidence': RESERVES['validation'] + RESERVES['upload'] + RESERVES['overhead'],
                 'validation': RESERVES['upload'] + RESERVES['overhead'], 'upload': RESERVES['overhead']}
        return self.hard_deadline - tails[phase]

    def enter(self, index):
        self.refresh()
        if self.poisoned or index != self.stage_index + 1:
            raise ValueError('Invalid/poisoned phase transition')
        if self.stage_index >= 0:
            self.finish_stage()
        stage = self.plan[index]
        later = sum(s['seconds'] for s in self.plan[index + 1:])
        origin = self.start if index == 0 else self.clock()
        self.deadline = min(origin + stage['seconds'], self.work_end - later)
        if self.deadline <= self.clock():
            raise TimeoutError('Required stage has no admitted time')
        self.stage_index, self.command_index = index, 0
        return self.deadline

    def admit(self, command):
        if self.poisoned:
            raise ValueError('Unclean/failed controller cannot launch another child')
        self.refresh()
        later_stages = sum(s['seconds'] for s in self.plan[self.stage_index + 1:])
        self.deadline = min(self.deadline, self.work_end - later_stages)
        steps = self.plan[self.stage_index]['commands']
        if self.command_index >= len(steps) or command != steps[self.command_index]:
            raise ValueError('Command differs from the exact stage sequence')
        later = sum(c['seconds'] for c in steps[self.command_index + 1:])
        now = self.clock()
        if now + command['seconds'] + later > self.deadline:
            raise TimeoutError('Insufficient budget preserving every later mandatory substep')
        end = now + command['seconds']
        event = {'id': command['id'], 'stage': self.plan[self.stage_index]['id'], 'started_monotonic': now,
                 'work_deadline': end - command['cleanup'], 'cleanup_deadline': end,
                 'later_required_substep_seconds': later, 'stage_deadline': self.deadline}
        self.events.append(event)
        self.command_index += 1
        return event

    def recheck(self, event, cleanup):
        self.refresh()
        later_stages = sum(s['seconds'] for s in self.plan[self.stage_index + 1:])
        self.deadline = min(self.deadline, self.work_end - later_stages)
        end = min(event['cleanup_deadline'], self.deadline - event['later_required_substep_seconds'])
        event['cleanup_deadline'] = end
        event['work_deadline'] = min(event['work_deadline'], end - cleanup)
        event['stage_deadline'] = self.deadline
        if self.poisoned or self.clock() >= event['work_deadline']:
            raise TimeoutError('Original allocation expired before native dispatch')
        return event

    def check_local(self, event):
        if self.clock() >= min(event['cleanup_deadline'], self.phase_end('work')):
            raise TimeoutError('Local validation exceeded its admitted substep')

    def finish_stage(self):
        if self.command_index != len(self.plan[self.stage_index]['commands']) or self.clock() > min(self.deadline, self.phase_end('work')):
            raise TimeoutError('Mandatory stage incomplete')

    def evidence_bounds(self, seconds, later, *, cleanup=20):
        now = self.clock()
        if self.evidence_end is None:
            self.evidence_end = min(now + RESERVES['evidence'], self.phase_end('evidence'))
        self.evidence_end = min(self.evidence_end, self.phase_end('evidence'))
        if self.poisoned or now + seconds + later > self.evidence_end:
            raise TimeoutError('Evidence command cannot preserve later extraction/validation')
        return now + seconds - cleanup, now + seconds
