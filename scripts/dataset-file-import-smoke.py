"""Opt-in real Parquet upload/confirm test; run in an isolated service container.

Uses existing official input files and harness images, no downloads or Agent calls.
The caller must provide a dedicated data mount, never the production data directory.
"""
import argparse
import hashlib
import json
import os
import threading
import time
import http.client
from urllib.parse import urlencode
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

import uvicorn
from worker.ctxbench_worker.api import create_app
from worker.ctxbench_worker.engine import create_engine_from_environment


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--ctxbench', type=Path, required=True)
    parser.add_argument('--swebench', type=Path, required=True)
    parser.add_argument('--ctxbench-sha256')
    parser.add_argument('--swebench-sha256')
    args = parser.parse_args()
    root = Path(os.environ['CTXBENCH_DATA_DIR']).resolve()
    if not root.name.startswith('ctxbench-file-import-test-'):
        raise SystemExit('A dedicated ctxbench-file-import-test-* data directory is required.')
    engine = create_engine_from_environment(root, 'docker')
    server = uvicorn.Server(uvicorn.Config(create_app(engine), host='127.0.0.1', port=48174, lifespan='off', access_log=False, log_level='warning'))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started: break
        time.sleep(.05)
    assert server.started, 'Isolated verification service failed to start'

    def request(method, path, params=None, content=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', 48174, timeout=660)
        connection.request(method, path + ('?' + urlencode(params) if params else ''), body=content, headers=headers or {})
        response = connection.getresponse()
        text = response.read().decode()
        connection.close()
        return SimpleNamespace(status_code=response.status, text=text, json=lambda: json.loads(text))

    client = SimpleNamespace(post=lambda path, **kwargs: request('POST', path, **kwargs), get=lambda path: request('GET', path))
    for benchmark, path, count in [('ctxbench', args.ctxbench, 138), ('swebench', args.swebench, 500)]:
        data = path.read_bytes()
        expected_hash = getattr(args, f'{benchmark}_sha256')
        if expected_hash:
            assert hashlib.sha256(data).hexdigest() == expected_hash, f'{benchmark} snapshot checksum mismatch'
        with patch.object(engine.runner, 'run', side_effect=AssertionError('Must not call an Agent')):
            preview = client.post('/v1/datasets/files/preview', params={'filename': path.name, 'name': f'File upload {benchmark}', 'benchmark': benchmark}, content=data, headers={'Content-Type': 'application/octet-stream'})
            assert preview.status_code == 200, preview.text
            receipt = preview.json()
            assert receipt['count'] == count, receipt['count']
            assert receipt['sha256'] == hashlib.sha256(data).hexdigest()
            assert receipt['testsExecuted'] is False
            assert all(set(item) == {'id', 'repository', 'baseCommit'} for item in receipt['samples'])
            result = client.post(f"/v1/datasets/files/{receipt['token']}/confirm")
            assert result.status_code == 201, result.text
            assert result.json()['count'] == count
            assert len(client.get(f"/v1/datasets/{result.json()['id']}/tasks").json()) == count
            assert not list((root / 'datasets').glob('upload-*'))
            print(json.dumps({'benchmark': benchmark, 'count': count, 'sha256': receipt['sha256'], 'imported': True, 'agentCalls': 0}))
    server.should_exit = True
    thread.join(timeout=10)


if __name__ == '__main__':
    main()
