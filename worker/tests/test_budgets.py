import tempfile
import threading
import unittest
from pathlib import Path

from worker.ctxbench_worker.budgets import TokenBudget, BudgetExhausted
from worker.ctxbench_worker.database import Database
from worker.ctxbench_worker.models import ModelConfig


class BudgetTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.database = Database(Path(temporary.name) / 'state.sqlite3')
        self.budget = TokenBudget(self.database)
        self.budget.create('round', 1000, 'mock', 'deterministic')

    def reserve(self, run_id, amount):
        return self.budget.reserve('round', run_id, amount, mode='solve', experiment_id='experiment', output='fixture')

    def test_immutable_limit_and_model(self):
        self.budget.create('round', 1000, 'mock', 'deterministic')
        with self.assertRaises(ValueError):
            self.budget.create('round', 1001, 'mock', 'deterministic')
        with self.assertRaises(ValueError):
            self.budget.validate('round', [ModelConfig('mock', 'different', 'off', 100)])

    def test_shared_reservation_and_idempotent_settlement(self):
        self.reserve('run-1', 800)
        with self.assertRaises(BudgetExhausted):
            self.reserve('run-2', 201)
        self.budget.settle('run-1', {'runId': 'run-1', 'budgetProtocolVersion': 1, 'status': 'completed',
                                   'cumulativeTokens': 80, 'sessionStats': {'tokens': {'total': 100}}})
        self.budget.settle('run-1', None)
        self.assertEqual(self.budget.snapshot('round')['chargedTokens'], 100)
        self.reserve('run-2', 900)
        self.assertEqual(self.budget.snapshot('round')['remainingTokens'], 0)

    def test_failure_and_crash_never_reset_spent_allowance(self):
        self.reserve('failed', 400)
        self.budget.settle('failed', {'runId': 'failed', 'status': 'failed', 'cumulativeTokens': 12})
        self.reserve('crashed', 500)
        recovered = TokenBudget(Database(self.database.path))
        recovered.recover(object())
        record = recovered.snapshot('round')
        self.assertEqual(record['chargedTokens'], 900)
        self.assertEqual(record['reportedTokens'], 12)
        self.assertEqual(record['unconfirmedTokens'], 900)
        self.assertEqual(record['reservedTokens'], 0)

    def test_atomic_reservation_across_connections(self):
        admitted = []
        def reserve(run_id):
            ledger = TokenBudget(Database(self.database.path))
            try:
                ledger.reserve('round', run_id, 600, mode='solve', experiment_id=None, output='fixture')
                admitted.append(run_id)
            except BudgetExhausted:
                pass
        workers = [threading.Thread(target=reserve, args=(f'run-{index}',)) for index in range(4)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()
        self.assertEqual(len(admitted), 1)

    def test_mimo_reserves_request_margin_and_malformed_usage_is_uncertain(self):
        budget = self.budget.create('mimo', 100_000_000, 'xiaomi-token-plan-cn', 'mimo-v2.5')
        self.assertEqual(budget['requestMarginTokens'], 2_359_296)
        self.budget.reserve('mimo', 'real', 300_000, mode='generate-context', experiment_id=None, output='fixture')
        self.budget.settle('real', {'status': 'completed', 'sessionStats': []})
        self.assertEqual(self.budget.snapshot('mimo')['chargedTokens'], 2_659_296)
