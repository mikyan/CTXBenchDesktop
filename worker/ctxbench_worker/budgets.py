"""Persistent, shared campaign admission and conservative usage accounting.

Reservations include two full model requests beyond a stage's cumulative limit.
Missing/interrupted usage retains the entire reservation; it is never zero cost.
This is a Provider-reported token guard, not a reconciliation of the Provider bill.
"""
from __future__ import annotations

import json
import re

from .database import Database, utc_now


class BudgetExhausted(Exception):
    pass


class TokenBudget:
    def __init__(self, database: Database):
        self.db = database

    def create(self, key: str, limit: int, provider: str, model: str) -> dict:
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', key) or type(limit) is not int or not 1 <= limit <= 10**12:
            raise ValueError('Invalid campaign budget ID or token limit.')
        if (provider, model) not in {('xiaomi-token-plan-cn', 'mimo-v2.5'), ('xiaomi-token-plan-cn', 'mimo-v2.5-pro'), ('mock', 'deterministic')}:
            raise ValueError('A verified model request bound is required for shared token budgeting.')
        margin = 0 if provider == 'mock' else 2 * (1_048_576 + 131_072)
        record = {'id': key, 'limitTokens': limit, 'provider': provider, 'model': model,
                  'requestMarginTokens': margin, 'createdAt': utc_now()}
        with self.db.connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            row = connection.execute("SELECT payload_json FROM documents WHERE kind='tokenBudgets' AND id=?", (key,)).fetchone()
            if row:
                existing = json.loads(row[0])
                if any(existing[field] != record[field] for field in ('limitTokens', 'provider', 'model', 'requestMarginTokens')):
                    raise ValueError('Campaign budgets are immutable; do not reset or increase an existing authorization.')
            else:
                connection.execute('INSERT INTO documents VALUES (?, ?, ?)', ('tokenBudgets', key, json.dumps(record)))
        return self.snapshot(key)

    def validate(self, key: str, profiles) -> dict:
        budget = self.db.get_document('tokenBudgets', key)
        if any((profile.provider, profile.model) != (budget['provider'], budget['model']) for profile in profiles):
            raise ValueError('Every billable role must use the Provider/model authorized by the shared budget.')
        return budget

    @staticmethod
    def _attempts(connection, key):
        return [json.loads(row[0]) for row in connection.execute(
            "SELECT payload_json FROM documents WHERE kind='tokenAttempts' AND json_extract(payload_json, '$.budgetId')=?", (key,))]

    @staticmethod
    def _totals(attempts):
        reserved = sum(item['reservedTokens'] for item in attempts if item['status'] == 'reserved')
        charged = sum(item.get('chargedTokens', 0) for item in attempts if item['status'] != 'reserved')
        reported = sum(item.get('reportedTokens', 0) for item in attempts)
        uncertain = sum(item.get('chargedTokens', 0) for item in attempts if item['status'] == 'unconfirmed')
        return {'reservedTokens': reserved, 'chargedTokens': charged, 'reportedTokens': reported,
                'unconfirmedTokens': uncertain, 'committedTokens': reserved + charged, 'attempts': len(attempts)}

    def snapshot(self, key: str) -> dict:
        budget = self.db.get_document('tokenBudgets', key)
        with self.db.connect() as connection:
            totals = self._totals(self._attempts(connection, key))
        return {**budget, **totals, 'remainingTokens': max(0, budget['limitTokens'] - totals['committedTokens'])}

    def reserve(self, key: str, run_id: str, stage_limit: int, *, mode: str, experiment_id: str | None, output: str) -> dict:
        if type(stage_limit) is not int or stage_limit <= 0:
            raise ValueError('Stage token limit must be positive.')
        with self.db.connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            budget_row = connection.execute("SELECT payload_json FROM documents WHERE kind='tokenBudgets' AND id=?", (key,)).fetchone()
            if budget_row is None:
                raise KeyError(key)
            budget = json.loads(budget_row[0])
            attempts = self._attempts(connection, key)
            if any(item['id'] == run_id for item in attempts):
                raise ValueError('Each paid attempt requires a fresh reservation ID.')
            amount = stage_limit + budget['requestMarginTokens']
            totals = self._totals(attempts)
            if totals['committedTokens'] + amount > budget['limitTokens']:
                raise BudgetExhausted(f"Shared token budget {key}: insufficient uncommitted allowance; execution paused without reducing paired stage budgets.")
            record = {'id': run_id, 'budgetId': key, 'mode': mode, 'experimentId': experiment_id,
                      'output': output, 'reservedTokens': amount, 'stageLimitTokens': stage_limit,
                      'status': 'reserved', 'createdAt': utc_now()}
            connection.execute('INSERT INTO documents VALUES (?, ?, ?)', ('tokenAttempts', run_id, json.dumps(record)))
        return record

    def settle(self, run_id: str, metadata: dict | None) -> dict:
        with self.db.connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            row = connection.execute("SELECT payload_json FROM documents WHERE kind='tokenAttempts' AND id=?", (run_id,)).fetchone()
            if row is None:
                raise KeyError(run_id)
            record = json.loads(row[0])
            if record['status'] != 'reserved':
                return record
            metadata = metadata or {}
            stats = metadata.get('sessionStats')
            stats = stats if isinstance(stats, dict) else {}
            tokens = stats.get('tokens')
            tokens = tokens if isinstance(tokens, dict) else {}
            values = [value for value in (metadata.get('cumulativeTokens'), tokens.get('total')) if type(value) is int and value >= 0]
            reported = max(values, default=0)
            complete = (metadata.get('runId') == run_id and metadata.get('budgetProtocolVersion') == 1
                        and metadata.get('status') == 'completed' and bool(values))
            record.update(status='settled' if complete else 'unconfirmed', reportedTokens=reported,
                          chargedTokens=reported if complete else max(reported, record['reservedTokens']), updatedAt=utc_now())
            connection.execute("UPDATE documents SET payload_json=? WHERE kind='tokenAttempts' AND id=?", (json.dumps(record), run_id))
        return record

    def recover(self, runner):
        # A crashed attempt is charged conservatively even if partial output survived.
        for attempt in self.db.list_documents('tokenAttempts'):
            if attempt['status'] == 'reserved':
                if hasattr(runner, 'cancel'):
                    runner.cancel(attempt['id'])
                self.settle(attempt['id'], None)
