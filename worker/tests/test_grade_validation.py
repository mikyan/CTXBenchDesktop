import logging
import runpy
import unittest
from pathlib import Path

validate = runpy.run_path(str(Path(__file__).resolve().parents[2] / 'docker' / 'official-harness' / 'grade_validation.py'))['require_agentbench_result']


class GradeValidationTests(unittest.TestCase):
    def test_normal_functional_failures_and_passes_are_preserved(self):
        self.assertFalse(validate(lambda: False))
        self.assertTrue(validate(lambda: True))
        with self.assertRaises(ValueError):
            validate(lambda: None)

    def test_upstream_swallowed_exception_cannot_become_a_model_failure(self):
        logger = logging.getLogger('agentbench.agentbench')
        original_handlers = list(logger.handlers)
        def swallowed_error():
            logger.error('Error during solving instance fixture: missing test_results.json')
            return False
        with self.assertRaisesRegex(RuntimeError, 'no functional verdict'):
            validate(swallowed_error)
        self.assertEqual(logger.handlers, original_handlers)
        self.assertFalse(validate(lambda: False), 'An earlier failure must not contaminate the next result')
