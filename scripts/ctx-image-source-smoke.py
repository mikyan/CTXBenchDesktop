"""Verify frozen CTX source handoff and official grading using cached images only.

Mount this repository at /source, official snapshots read-only at /datasets and
the Docker socket. No baseline dependency download, Provider key or model call.
"""
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

import docker
import pyarrow.parquet as pq

sys.path.insert(0, '/source/docker/official-harness')
from agentbench_environment import prepare_environment, setup_identity
from harness import grade_agentbench
from policy import configure


def main():
    client = docker.from_env()
    try:
        row = next(row for row in pq.read_table('/datasets/agentbench.parquet').to_pylist() if row['instance_id'] == 'opshin_opshin-28')
        source = client.images.get(row['docker_image']).id
        identity = setup_identity(row, source)
        key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        try:
            expected = client.images.get('ctxbench/agentbench-env:' + key).id
        except docker.errors.ImageNotFound:
            raise RuntimeError('Cached baseline-specific environment unavailable; refusing to download dependencies in this smoke test.')
        os.environ['CTXBENCH_LOCAL_IMAGES_ONLY'] = '1'
        configure()
        with tempfile.TemporaryDirectory(prefix='ctxbench-source-check-') as directory:
            root = Path(directory)
            # A deliberately non-existent original name catches accidental fallback.
            manifest = prepare_environment({**row, 'docker_image': 'registry.invalid/must-not-pull:latest'}, root / 'prepare', source)
            assert manifest['imageId'] == expected
            dataset = root / 'dataset.json'; dataset.write_text(json.dumps([row], default=str))
            gold = root / 'gold.patch'; gold.write_text(row['clean_pr_patch'])
            result = root / 'grade'
            grade_agentbench(dataset, row['instance_id'], gold, result, manifest['imageId'])
            assert json.loads((result / 'summary.json').read_text())['resolved']
            print(json.dumps({'instance': row['instance_id'], 'sourceImage': source, 'graderImage': expected,
                              'referenceResolved': True, 'modelCalls': 0, 'sourceFallback': False}))
    finally:
        scope = os.environ.get('CTXBENCH_GRADE_SCOPE')
        if scope:
            for child in client.containers.list(all=True, filters={'label': 'io.ctxbench.grade-scope=' + scope}):
                child.remove(force=True)
        client.close()


if __name__ == '__main__':
    main()
