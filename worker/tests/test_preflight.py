import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from worker.ctxbench_worker.models import ExperimentSpec, ModelConfig, ResourcePolicy
from worker.ctxbench_worker.preflight import estimate, storage_status


class PreflightTests(unittest.TestCase):
    def test_counts_roles_without_double_charging_shared_context_key(self):
        model = ModelConfig('mock', 'fixture', 'off', 100)
        spec = ExperimentSpec('Example', 'custom', 'dataset', ('none', 'skill-generated'), 2,
            ('one', 'two'), model, 'image', ResourcePolicy(), 1, evaluate_constraints=True)
        tasks = [SimpleNamespace(id=name, repository='repo', base_commit='a' * 40) for name in spec.task_ids]
        result = estimate(spec, tasks)
        self.assertEqual((result['runs'], result['builderInvocations'], result['minerInvocations'], result['judgeInvocations']), (8, 1, 1, 24))
        self.assertEqual(result['configuredTokenAllowance'], 3400)
        multi = estimate(replace(spec, builder_workflow={'steps': [{'prompt': None}] * 2}, solver_workflow={'steps': [{'prompt': None}] * 3}), tasks)
        self.assertEqual((multi['builderPromptSteps'], multi['solverPromptSteps']), (2, 24))
        self.assertEqual(multi['configuredTokenAllowance'], 3400)
        result = estimate(replace(spec, arms=('none', 'manual'), constraint_packages={'one': 'package', 'two': 'package'}), tasks)
        self.assertEqual(result['configuredTokenAllowance'], 3200)

    def test_storage_guard_reads_actual_capacity_and_honors_threshold(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict('os.environ', {'CTXBENCH_MIN_FREE_GB': '5'}):
            with patch('worker.ctxbench_worker.preflight.shutil.disk_usage', return_value=SimpleNamespace(free=1024, total=2048)):
                self.assertFalse(storage_status(Path(directory))['ready'])
