"""Closed fresh-VM normal/system-largest row identities, never inferred from results."""
import os
import re
from vision_suites import CASES as VISION_CASES

PHASES = ('normal', 'system-largest')
LARGEST_VISION_CASES = ('chinese', 'canvas-audit')
PROFILES = ('smallest', 'largest')


def row(platform, phase, case, profile, sha):
    if platform not in ('vision', 'watch') or phase not in PHASES:
        raise ValueError('Unknown native text row platform/phase')
    if not isinstance(sha, str) or not re.fullmatch('[0-9a-f]{40}', sha):
        raise ValueError('Missing exact native text source')
    if platform == 'vision':
        if profile != '' or case not in VISION_CASES or (phase == 'system-largest' and case not in LARGEST_VISION_CASES):
            raise ValueError('Unknown Vision text row case/profile')
        lane = 'vision-' + case
        budget = VISION_CASES[case][1] if phase == 'normal' else 700_000
        minutes = 25
    else:
        if case != '' or profile not in PROFILES:
            raise ValueError('Unknown Watch text row case/profile')
        lane = 'watch-' + profile
        budget = 1_200_000 if phase == 'normal' else 600_000
        minutes = 45
    if phase == 'system-largest': lane += '-system-largest'
    return {'schema': 1, 'platform': platform, 'phase': phase, 'case': case, 'profile': profile,
            'lane': lane, 'source_sha': sha, 'minutes': minutes, 'evidence_bytes': budget}


def validate(binding, *, sha=None):
    if not isinstance(binding, dict): raise ValueError('Missing exact native text row binding')
    expected = row(binding.get('platform'), binding.get('phase'), binding.get('case'), binding.get('profile'), binding.get('source_sha'))
    if binding != expected or any(type(binding.get(key)) is not int for key in ('schema', 'minutes', 'evidence_bytes')):
        raise ValueError('Native text row contract changed')
    if sha is not None and binding['source_sha'] != sha: raise ValueError('Native text row source changed')
    return expected


def from_environment(platform, sha, environ=None):
    environ = os.environ if environ is None else environ
    binding = row(platform, environ.get('TOUCHCOLOR_TEXT_PHASE'), environ.get('TOUCHCOLOR_VISION_CASE', ''),
                  environ.get('TOUCHCOLOR_WATCH_PROFILE', ''), sha)
    if (environ.get('TOUCHCOLOR_JOB_PLATFORM') != platform or environ.get('GITHUB_SHA') != sha
            or environ.get('TOUCHCOLOR_JOB_LANE') != binding['lane']
            or environ.get('TOUCHCOLOR_JOB_MINUTES') != str(binding['minutes'])
            or environ.get('TOUCHCOLOR_EVIDENCE_LIMIT') != str(binding['evidence_bytes'])):
        raise ValueError('Native text row differs from current job/source')
    return binding


def report_binding(report, environ=None):
    environ = os.environ if environ is None else environ
    binding = validate(report.get('native_text_row'))
    if binding['source_sha'] != report.get('sha'): raise ValueError('Native text report source changed')
    if environ.get('TOUCHCOLOR_JOB_PLATFORM') in ('vision', 'watch'):
        if binding != from_environment(binding['platform'], report.get('sha'), environ):
            raise ValueError('Saved native text row differs from current row')
    return binding


def vision_roles(binding):
    validate(binding)
    if binding['platform'] != 'vision': raise ValueError('Vision result has another row platform')
    return ['hosted', 'normal' if binding['phase'] == 'normal' else 'largest']
