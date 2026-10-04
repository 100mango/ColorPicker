"""Static safety contracts only; actual public AX calls require the Mac CI lane."""
from pathlib import Path
import json
import os
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class MacActionDiagnosticContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT/'TouchColorMacUITests/TouchColorMacUITests.swift').read_text()
        cls.helper = cls.source.split('    private func recordAuditActions(', 1)[1].split('    private func recordAuditOwnership(', 1)[0]

    def test_only_public_reads_and_object_local_timeout_are_used(self):
        self.assertIn('AXUIElementCopyActionNames(node, &names)', self.helper)
        self.assertIn('AXUIElementSetMessagingTimeout(node, 0.15)', self.helper)
        self.assertIn('guard AXIsProcessTrusted() else', self.helper)
        for forbidden in ('AXUIElementPerformAction', 'AXUIElementSetAttributeValue', 'AXIsProcessTrustedWithOptions',
                          'AXMakeProcessTrusted', 'AXUIElementCreateSystemWide', 'XCTFail(', 'XCTAssert', 'return true'):
            self.assertNotIn(forbidden, self.helper)

    def test_exact_pid_and_adjacent_build_own_every_inspected_node(self):
        self.assertIn('actual.bundleURL?.resolvingSymlinksInPath() == expectedURL', self.helper)
        self.assertIn('running.count == 1', self.helper)
        self.assertIn('AXUIElementCreateApplication(pid)', self.helper)
        self.assertIn('AXUIElementGetPid(node, &owner) == .success, owner == pid', self.helper)
        self.assertLess(self.helper.index('visited.append(node); try owned(node)'), self.helper.index('let identifier = try value(node'))
        self.assertIn('children(root, kAXWindowsAttribute, limit: 4)', self.helper)

    def test_target_has_exact_identifier_role_and_finite_matching_geometry(self):
        self.assertIn('expectedRole = NSAccessibility.Role.link.rawValue', self.helper)
        self.assertNotIn('kAXLinkRole', self.helper)
        for required in ('target.identifier == "palette.actions.0"', 'target.elementType == .menuButton',
                         'target.identifier == "mailto:100mango@gmail.com"', 'target.identifier == "privacy.contact"',
                         'target.elementType == .link',
                         'frame.width > 0, frame.height > 0', '.allSatisfy({ $0.isFinite })',
                         'identifier == target.identifier, role == expectedRole',
                         'abs(bounds.minX - frame.minX) <= 0.5', 'abs(bounds.minY - frame.minY) <= 0.5',
                         'abs(bounds.width - frame.width) <= 0.5', 'abs(bounds.height - frame.height) <= 0.5'):
            self.assertIn(required, self.helper)

    def test_read_work_and_metadata_have_explicit_finite_caps(self):
        for required in ('actionDiagnosticKeys.count < 4', 'data.count <= 8192', 'guard calls <= 510',
                         'systemUptime - start < 2', 'calls += 2', 'visited.count < 128', 'depth < 16',
                         'kAXChildrenAttribute, limit: 16', 'matches.count >= 4', '.prefix(16)', '$0.prefix(128)'):
            self.assertIn(required, self.helper)

    def test_partial_child_arrays_and_unreadable_candidate_geometry_are_incomplete(self):
        children = self.helper.split('func children(', 1)[1].split('func geometry(', 1)[0]
        self.assertIn('values.count == min(count, limit)', children)
        self.assertNotIn('values.count <= limit', children)
        self.assertIn('incomplete = true; return []', children)
        geometry = self.helper.split('func geometry(', 1)[1].split('            do {', 1)[0]
        self.assertEqual(geometry.count('else { incomplete = true; return nil }'), 2)
        self.assertNotIn('else { return nil }', geometry)
        self.assertIn('let bounds = try geometry(node)', self.helper)
        self.assertIn('!incomplete && matches.count == 1', self.helper)

    def test_partial_failed_or_ambiguous_action_reads_do_not_claim_complete(self):
        self.assertIn('code == .success && actions != nil && actions!.count <= 16', self.helper)
        self.assertIn('!incomplete && matches.count == 1 && (matches[0]["actionsComplete"] as? Bool) == true', self.helper)
        self.assertIn('"partial_or_unavailable"', self.helper)
        self.assertIn('"AX client is not trusted; no prompt requested"', self.helper)
        self.assertIn('"auditID": auditID', self.helper)
        self.assertIn('Native Mac accessibility issue action names ', self.helper)

    def test_diagnostic_never_handles_or_suppresses_audit_issue(self):
        audit = self.source.split('    @MainActor private func audit(', 1)[1].split('    private func recordAuditActions(', 1)[0]
        self.assertIn('self.recordAuditActions(element, state: state, auditID: auditID)', audit)
        self.assertIn('try app.performAccessibilityAudit(for: .all)', audit)
        self.assertIn('return false', audit)
        self.assertNotIn('return true', audit)

    def test_action_metadata_survives_retention_without_changing_raw_issue_count(self):
        from test_retain_mac_evidence import Fixture, SOURCE
        import retain_mac_evidence as keep
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'GITHUB_SHA': ''}):
            root = Path(tmp); fixture = Fixture(root)
            group, _, _, proof = fixture.proof('full image and palette')
            data = json.dumps({'auditID': proof['auditID'], 'state': 'full image and palette',
                               'status': 'unavailable', 'reason': 'Synthetic untrusted client'}).encode()
            name = fixture.add(group, 'Native Mac accessibility issue action names ' + proof['auditID'], data, '.txt', 44)
            fixture.save(); keep.retain(root, SOURCE)
            self.assertEqual((root/name).read_bytes(), data)
            self.assertTrue(keep.validate_selection(root, require_complete=True)['complete'])


if __name__ == '__main__': unittest.main()
