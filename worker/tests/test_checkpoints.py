import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from worker.ctxbench_worker.checkpoints import GradeCheckpoint, atomic_json, stage_evidence, verify_stage


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_grade_is_bound_to_inputs_and_preserves_rejected_evidence(self):
        checkpoint = GradeCheckpoint(self.root, 'original')
        checkpoint.save({'resolved': True, 'detail': '中文证据'})
        self.assertTrue(checkpoint.load()['resolved'])
        self.assertIsNone(GradeCheckpoint(self.root, 'changed-inputs').load())
        self.assertEqual(len(list(self.root.glob('rejected-summary-*.json'))), 1)

    def test_corrupt_or_forged_grade_requires_regrade(self):
        checkpoint = GradeCheckpoint(self.root, 'inputs')
        checkpoint.save({'resolved': True})
        (self.root / 'summary.json').write_text('{truncated')
        self.assertIsNone(checkpoint.load())
        checkpoint.save({'resolved': False})
        (self.root / 'summary.json').write_text(json.dumps({'resolved': True}))
        self.assertIsNone(checkpoint.load())

    def test_disk_full_does_not_replace_completed_checkpoint(self):
        checkpoint = GradeCheckpoint(self.root, 'inputs')
        checkpoint.save({'resolved': True})
        with patch('worker.ctxbench_worker.checkpoints.os.replace', side_effect=OSError(28, 'No space left')):
            with self.assertRaises(OSError):
                atomic_json(self.root, 'summary.json', {'resolved': False})
        self.assertTrue(checkpoint.load()['resolved'])
        self.assertFalse(list(self.root.glob('*.tmp')))

    def test_completed_solver_patch_tampering_is_rejected(self):
        stage = {'output': str(self.root), 'workspace': str(self.root)}
        (self.root / 'result.json').write_text('{}')
        (self.root / 'graded.patch').write_text('original')
        self.assertEqual(verify_stage(stage, 'solve'), 'legacy-unverified')
        stage['integrity'] = stage_evidence(stage, 'solve')
        self.assertEqual(verify_stage(stage, 'solve'), 'verified')
        (self.root / 'graded.patch').write_text('tampered')
        with self.assertRaisesRegex(ValueError, 'evidence has changed'):
            verify_stage(stage, 'solve')
