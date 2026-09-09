"""Verify a real legacy JSON dataset in an isolated library, without model calls.

Usage: python scripts/case-library-import-smoke.py SOURCE.json EMPTY_OUTPUT_DIR
       [--benchmark ctxbench|swebench|custom]

Mount the source read-only when running in Docker. This test never opens the
production database or starts the scheduler. It preserves complete grading rows
in its own scratch database and prints only counts, sizes and verification flags.
"""
import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from worker.ctxbench_worker.engine import create_mock_engine
from worker.ctxbench_worker.workbench import Workbench


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--benchmark', choices=('ctxbench', 'swebench', 'custom'), default='ctxbench')
    args = parser.parse_args()
    source, root = args.source.resolve(), args.output.resolve()
    if not root.is_dir() or any(root.iterdir()) or source.is_relative_to(root):
        parser.error('Use an existing empty scratch output directory, separate from the source.')
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    rows = json.loads(source.read_text(encoding='utf-8'))
    assert isinstance(rows, list) and rows
    engine = create_mock_engine(root)
    wb = Workbench(engine, None)
    wb.catalog.register('Isolated legacy import', args.benchmark, rows)
    start = time.monotonic()
    inventory = wb.library.inventory()
    load_seconds = time.monotonic() - start
    assert not inventory['importWarnings'], inventory['importWarnings']
    assert len(inventory['cases']) == len(rows)
    assert len(inventory['sets']) == 1 and inventory['sets'][0]['count'] == len(rows)
    sizes = [len(json.dumps(row, ensure_ascii=False, separators=(',', ':')).encode('utf-8')) for row in rows]
    worst = sizes.index(max(sizes))
    case_id = inventory['sets'][0]['caseIds'][worst]
    detail = wb.library.case(case_id)
    assert detail['row'] == rows[worst]
    wb.library.save_case({'name': 'Renamed large case', 'benchmark': args.benchmark,
        'row': detail['row'], 'expectedRevision': detail['revision']}, case_id)
    frozen, receipt = wb.library.freeze(case_id)
    frozen_row = json.loads((root / 'datasets' / f'{frozen}.json').read_text(encoding='utf-8'))
    assert frozen_row == [rows[worst]] and receipt['members'][0]['revision'] == 2
    wb.library.save_case({'name': 'Independent new case', 'benchmark': 'custom', 'row': {
        'id': 'independent-startup-case', 'repository': 'https://git.example/team/service.git',
        'baseCommit': 'a' * 40, 'prompt': 'Repair the service behavior.', 'image': 'company/test:v1',
        'test': {'command': ['python3', '-m', 'unittest']}}})
    restored = Workbench(engine, None).library.inventory()
    assert len(restored['cases']) == len(rows) + 1 and len(restored['sets']) == 1
    assert not restored['importWarnings']
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    summary = {'status': 'passed', 'benchmark': args.benchmark, 'sourceCases': len(rows),
        'over10MB': sum(size > 10_000_000 for size in sizes), 'maxCaseBytes': max(sizes),
        'initialLoadSeconds': round(load_seconds, 3), 'sourceUnchanged': True,
        'largeCaseEditAndSnapshotPreserved': True, 'independentCreation': True,
        'restartWithoutDuplicates': True, 'modelCalls': 0}
    (root / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(summary))


if __name__ == '__main__':
    main()
