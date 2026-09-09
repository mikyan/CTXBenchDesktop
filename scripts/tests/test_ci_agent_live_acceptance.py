"""Offline checks only: importing the paid acceptance must not execute it."""
import importlib.util
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


spec = importlib.util.spec_from_file_location('ci_agent_acceptance',
    Path(__file__).resolve().parents[1] / 'ci-agent-live-acceptance.py')
acceptance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acceptance)


class AgentAcceptanceSafetyTests(unittest.TestCase):
    def test_export_preserves_utf8_and_lf_patch_bytes(self):
        content = 'diff --git a/a b/a\n-旧\n+新\n'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'candidate.patch'
            acceptance.save_text(path, content)
            self.assertEqual(path.read_bytes(), content.encode('utf-8'))

    def test_subprocess_failure_does_not_echo_credentials_or_arguments(self):
        secret = 'acceptance-unit-test-secret'
        result = SimpleNamespace(returncode=1, stdout=secret, stderr=secret)
        with patch.object(acceptance.subprocess, 'run', return_value=result):
            with self.assertRaises(RuntimeError) as raised:
                acceptance.command(['gh', 'sensitive-command', secret])
        self.assertNotIn(secret, str(raised.exception))
        self.assertNotIn('sensitive-command', str(raised.exception))


if __name__ == '__main__':
    unittest.main()
