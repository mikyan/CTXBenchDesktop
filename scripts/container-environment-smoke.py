"""Isolated multi-variable Docker acceptance; never calls a Provider or changes production credentials.

Run in the worker image with /source:ro, /var/lib/ctxbench and the Docker socket mounted.
"""
import hashlib
import io
import json
import os
import socket
import sys
import threading
import time
import urllib.request
import uuid
from pathlib import Path

import docker
import uvicorn


def main():
    root = Path('/var/lib/ctxbench') / f'acceptance-environment-{uuid.uuid4().hex[:10]}'
    os.environ['CTXBENCH_DATA_DIR'] = str(root / 'default')
    os.environ['CTXBENCH_RUNNER'] = 'mock'
    sys.path.insert(0, '/source')
    from worker.ctxbench_worker.api import create_app
    from worker.ctxbench_worker.engine import create_mock_engine
    from worker.ctxbench_worker.models import ModelConfig, ResourcePolicy, RunSpec
    from worker.ctxbench_worker.runner import DockerRunner

    engine = create_mock_engine(root)
    engine.runner = DockerRunner(root / 'repositories', root / 'runs', root / 'requests',
                                 worker_data_root=root, host_data_root=str(root))
    # Values are fresh synthetic sentinels, not credentials from the host or deployment.
    variables = {
        'INTERNAL_AGENT_KEY': f'fixture-{uuid.uuid4().hex}',
        'INTERNAL_AGENT_URL': 'https://provider.invalid/v1?example=1',
        'INTERNAL_AGENT_TENANT': f'tenant-{uuid.uuid4().hex}',
    }
    # Exercise HTTP with the production runtime's dependencies, without starting queued work.
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    server = uvicorn.Server(uvicorn.Config(create_app(engine), lifespan='off', access_log=False, log_level='error'))
    thread = threading.Thread(target=server.run, kwargs={'sockets': [listener]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert server.started, 'Isolated HTTP server did not start'
        request = urllib.request.Request(f'http://127.0.0.1:{listener.getsockname()[1]}/v1/runtime/credentials',
            data=json.dumps({'variables': [{'name': name, 'value': value} for name, value in variables.items()]}).encode(),
            headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=10) as response:
            body = response.read().decode()
            assert response.status == 200, 'Batch API rejected synthetic variables'
            assert all(value not in body for value in variables.values()), 'API exposed a value'
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        listener.close()

    probe = '''import hashlib, json, os
from pathlib import Path
names = ("INTERNAL_AGENT_KEY", "INTERNAL_AGENT_URL", "INTERNAL_AGENT_TENANT")
assert "UNSELECTED_ENV_FIXTURE" not in os.environ
assert all(os.environ.get(name) for name in names)
request = Path("/ctxbench/request.json").read_text()
assert all(os.environ[name] not in request for name in names)
Path("/ctxbench/output/probe.json").write_text(json.dumps({name: hashlib.sha256(os.environ[name].encode()).hexdigest() for name in names}))
print(" ".join(os.environ[name] for name in names))
'''
    client = docker.from_env()
    image = None
    try:
        parent = client.images.get('ctxbench/agent-pi:0.1.0').id
        dockerfile = f'FROM {parent}\nENTRYPOINT {json.dumps(["python3", "-c", probe])}\n'
        image, _ = client.images.build(fileobj=io.BytesIO(dockerfile.encode()), rm=True, pull=False, network_mode='none')
        workspace = root / 'repositories' / 'fixture'
        workspace.mkdir()
        os.environ['UNSELECTED_ENV_FIXTURE'] = 'must-not-be-forwarded'
        # Even an allowlisted variable must not be injected unless the run selected it.
        engine.runner.env_allowlist |= {'UNSELECTED_ENV_FIXTURE'}
        result = engine.runner.run(RunSpec(
            'multi-environment', 'solve', image.id, str(workspace), str(root / 'runs' / 'probe'),
            'Synthetic environment propagation check', ModelConfig('mock', 'deterministic', 'off', 10),
            ResourcePolicy(cpus=1, memory_gb=1, timeout_minutes=1, network='offline'), env_names=tuple(variables),
        ))
        assert result.status == 'completed', 'Container propagation probe failed; inspect isolated acceptance output'
        hashes = json.loads((Path(result.output_dir) / 'probe.json').read_text())
        assert hashes == {name: hashlib.sha256(value.encode()).hexdigest() for name, value in variables.items()}
        logs = (Path(result.output_dir) / 'container.log').read_text()
        assert logs.count('[REDACTED]') == len(variables)
        assert all(value not in logs for value in variables.values()), 'Container log exposed a value'
        print(json.dumps({'status': 'passed', 'variables': len(variables), 'unselectedExcluded': True,
                          'logsRedacted': True, 'providerCalls': 0, 'root': str(root)}))
    finally:
        if image is not None:
            client.images.remove(image.id)
        client.close()


if __name__ == '__main__':
    main()
