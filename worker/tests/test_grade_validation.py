import logging
import json
import runpy
import unittest
from types import SimpleNamespace
from pathlib import Path

validate = runpy.run_path(str(Path(__file__).resolve().parents[2] / 'docker' / 'official-harness' / 'grade_validation.py'))['require_agentbench_result']
run_tests = runpy.run_path(str(Path(__file__).resolve().parents[2] / 'docker' / 'official-harness' / 'grade_validation.py'))['run_test_commands']


class GradeValidationTests(unittest.TestCase):
    def test_test_failure_with_valid_report_is_not_an_infrastructure_error(self):
        scripts = []
        env = SimpleNamespace(execute=lambda script, **kwargs: scripts.append(script) or {'returncode': 1, 'output': 'assertion failed'},
                              read_file=lambda name: '{"test_one":false}')
        self.assertEqual(run_tests(env, ['source .venv/bin/activate', 'python run_tests.py'], 'test_results.json'), {'test_one': False})
        self.assertEqual(len(scripts), 1)
        self.assertIn('source .venv/bin/activate\nset +e\npython run_tests.py', scripts[0])

    def test_missing_empty_or_malformed_report_never_becomes_a_pass(self):
        for raw in ('', '{}', '[]', '{"test":1}', '{"test":"false"}', '{"":true}', 'invalid'):
            with self.subTest(raw=raw):
                env = SimpleNamespace(execute=lambda *args, **kwargs: {'returncode': 1, 'output': 'ModuleNotFoundError: pytest'}, read_file=lambda name: raw)
                with self.assertRaisesRegex(RuntimeError, 'no functional verdict.*ModuleNotFoundError: pytest'):
                    run_tests(env, ['python run_tests.py'], 'test_results.json')

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
