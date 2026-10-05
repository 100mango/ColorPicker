#!/bin/bash
set -euo pipefail
family="${1:?Provide iPhoneCompact, iPhoneLarge, iPadLarge or iPadMini}"
suite="${2:?Provide prepare, prepare-unit, seed, shutdown, TouchColorTests, TouchColorUITests or AccessibilityAudits}"
case "$family" in iPhoneCompact|iPhoneLarge|iPadLarge|iPadMini) ;; *) exit 2;; esac
case "$suite" in prepare|prepare-unit|seed|shutdown|TouchColorTests|TouchColorUITests|AccessibilityAudits|configure|fixture-seed|managed-hosted|managed-functional|managed-audits|managed-shutdown) ;; *) exit 2;; esac
if [[ -e "build/$family-runtime-command-uncertain" || -L "build/$family-runtime-command-uncertain" ]]; then
  echo 'BLOCKED: an owned simulator command has no confirmed timely exit; no later simulator action is permitted' >&2
  exit 3
fi
# Closed canonical hosted-first route. Legacy/native paired callers below keep
# their original suite commands and preparation behavior.
if [[ "$suite" == configure || "$suite" == fixture-seed || "$suite" == managed-* ]]; then
  if [[ "$suite" == managed-functional && ( "$family" == iPhoneLarge || "$family" == iPhoneCompact ) ]]; then
    python3 "$(dirname -- "$0")/uikit_managed_tests.py" "$family" "$suite" 2>&1 | python3 "$(dirname -- "$0")/palette_lifecycle_diagnostics.py" retain "$family"
  else
    exec python3 "$(dirname -- "$0")/uikit_managed_tests.py" "$family" "$suite"
  fi
  exit
fi
if [[ "$suite" == prepare || "$suite" == prepare-unit || "$suite" == seed || "$suite" == shutdown ]]; then
  exec python3 "$(dirname -- "$0")/uikit_warmup.py" "$family" "$suite"
fi
# Validate the existing owned binding and bound all pre-test simctl commands.
# XCTest arguments, timing and exit status below remain unchanged.
device=$(python3 "$(dirname -- "$0")/uikit_warmup.py" "$family" "$suite")
if [[ -e "build/$family-runtime-command-uncertain" || -L "build/$family-runtime-command-uncertain" ]]; then
  echo 'BLOCKED: an owned simulator command has no confirmed timely exit' >&2
  exit 3
fi
selection="$suite"
if [[ "$suite" == TouchColorUITests ]]; then
  if [[ "$family" == iPadLarge || "$family" == iPadMini ]]; then selection="TouchColorUITests/TouchColorIPadUITests"; else selection="TouchColorUITests/TouchColorUITests"; fi
fi
if [[ "$suite" == AccessibilityAudits ]]; then selection="TouchColorUITests/TouchColorAccessibilityUITests"; fi
run_test_suite() {
xcodebuild -project TouchColor.xcodeproj -scheme TouchColor -configuration Debug \
  -destination "platform=iOS Simulator,id=$device" -derivedDataPath build/simulator \
  -resultBundlePath "build/$family-$suite.xcresult" -parallel-testing-enabled NO \
  -collect-test-diagnostics never -test-timeouts-enabled YES -default-test-execution-time-allowance 180 \
  -maximum-test-execution-time-allowance 240 -only-testing:"$selection" \
  test-without-building
}
# Retain only exact target-case correlation metadata; pipefail preserves real
# test failure. Unit/iPad/audit output and application behavior are unchanged.
if [[ "$suite" == TouchColorUITests && ( "$family" == iPhoneLarge || "$family" == iPhoneCompact ) ]]; then
  run_test_suite 2>&1 | python3 "$(dirname -- "$0")/palette_lifecycle_diagnostics.py" retain "$family"
else
  run_test_suite
fi
