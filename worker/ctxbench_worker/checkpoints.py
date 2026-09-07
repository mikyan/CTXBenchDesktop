"""Immutable agent evidence and recoverable, input-bound grader checkpoints."""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path

from .safe_files import safe_file


def digest(root: Path, relative: str) -> str:
    return hashlib.sha256(safe_file(root, relative).read_bytes()).hexdigest()


def stage_evidence(stage: dict, mode: str) -> dict:
    output, workspace = Path(stage['output']), Path(stage['workspace'])
    names = ['result.json']
    names += [name for name in ('workflow.json', 'setup.log') if safe_file(output, name).exists()]
    if mode == 'solve':
        names += ['graded.patch']
        names += [name for name in ('raw_agent.patch', 'context_mutation.patch') if safe_file(output, name).exists()]
    elif mode == 'generate-context':
        names += sorted(path.relative_to(output).as_posix() for path in (output / 'context' / 'files').rglob('*') if path.is_file())
    workspace_names = {'mine-constraints': ['constraints.json'], 'judge-constraints': ['votes.json']}.get(mode, [])
    return {'version': 1, 'output': {name: digest(output, name) for name in names},
            'workspace': {name: digest(workspace, name) for name in workspace_names}}


def verify_stage(stage: dict, mode: str) -> str:
    if not stage.get('integrity'):
        # Do not silently relabel old checkpoints as verified evidence.
        return 'legacy-unverified'
    if stage_evidence(stage, mode) != stage['integrity']:
        raise ValueError('Completed stage evidence has changed; cached results cannot be reused.')
    return 'verified'


def atomic_json(root: Path, name: str, value: dict) -> None:
    root.mkdir(parents=True, exist_ok=True)
    destination = safe_file(root, name)
    temporary = safe_file(root, f'.checkpoint-{uuid.uuid4().hex}.tmp')
    try:
        with temporary.open('x', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


class GradeCheckpoint:
    def __init__(self, root: Path, binding: str):
        self.root, self.binding = root, binding

    def load(self) -> dict | None:
        summary = safe_file(self.root, 'summary.json')
        receipt = safe_file(self.root, 'checkpoint.json')
        if not summary.exists():
            return None
        try:
            metadata = json.loads(receipt.read_text(encoding='utf-8'))
            value = json.loads(summary.read_text(encoding='utf-8'))
            if metadata.get('version') == 1 and metadata.get('binding') == self.binding and metadata.get('summaryHash') == digest(self.root, 'summary.json') and isinstance(value.get('resolved'), bool):
                return value
        except (OSError, ValueError, AttributeError):
            pass
        # Keep rejected output for audit, then allow regrading without repaying the solver.
        rejected = safe_file(self.root, f'rejected-summary-{uuid.uuid4().hex}.json')
        rejected.write_bytes(summary.read_bytes())
        return None

    def save(self, summary: dict) -> None:
        if not isinstance(summary.get('resolved'), bool):
            raise ValueError('Grader checkpoint requires a boolean resolution.')
        atomic_json(self.root, 'summary.json', summary)
        atomic_json(self.root, 'checkpoint.json', {'version': 1, 'binding': self.binding,
                    'summaryHash': digest(self.root, 'summary.json')})
