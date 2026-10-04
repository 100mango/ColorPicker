import base64
import hashlib
import json
import unittest
from decode_log_screenshots import decode_screenshots


class ScreenshotEnvelopeTests(unittest.TestCase):
    # Synthetic bytes test transport parsing only; these are not app screenshots.
    data = b'\xff\xd8' + b'synthetic-transport-fixture' * 230 + b'\xff\xd9'

    def envelope(self, *, metadata=True, bad_digest=False, omit_chunk=False):
        name = 'iPhoneCompact-test-evidence'
        value = dict(name=name, bytes=len(self.data), sha256='0' * 64 if bad_digest else hashlib.sha256(self.data).hexdigest())
        lines = ['SCREENSHOT_META:' + json.dumps(value)] if metadata else []
        lines.append('SCREENSHOT_BEGIN:' + name)
        encoded = base64.b64encode(self.data).decode('ascii')
        chunks = [encoded[offset:offset + 4096] for offset in range(0, len(encoded), 4096)]
        for index, chunk in enumerate(chunks):
            if omit_chunk and index == 0:
                continue
            lines.append(('\ufeff' if index == 1 else '') + '2026-10-03T22:48:04.123Z SCREENSHOT_CHUNK:' + chunk)
        lines.append('2026-10-03T22:48:05.123Z SCREENSHOT_END:' + name)
        return '\n'.join(lines)

    def test_bom_in_middle_preserves_every_chunk_and_matches_producer_digest(self):
        [(metadata, data)] = decode_screenshots(self.envelope())
        self.assertEqual(data, self.data)
        self.assertTrue(metadata['producer_integrity_verified'])

    def test_missing_chunk_is_rejected(self):
        with self.assertRaises(ValueError):
            decode_screenshots(self.envelope(omit_chunk=True))

    def test_wrong_digest_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'integrity mismatch'):
            decode_screenshots(self.envelope(bad_digest=True))

    def test_legacy_requires_explicit_unverified_mode(self):
        with self.assertRaisesRegex(ValueError, 'required'):
            decode_screenshots(self.envelope(metadata=False))
        [(metadata, data)] = decode_screenshots(self.envelope(metadata=False), True)
        self.assertEqual(data, self.data)
        self.assertFalse(metadata['producer_integrity_verified'])

    def test_duplicate_and_unclosed_envelopes_are_rejected(self):
        with self.assertRaises(ValueError):
            decode_screenshots(self.envelope() + '\n' + self.envelope())
        with self.assertRaises(ValueError):
            decode_screenshots(self.envelope().split('SCREENSHOT_END:')[0])


if __name__ == '__main__':
    unittest.main()
