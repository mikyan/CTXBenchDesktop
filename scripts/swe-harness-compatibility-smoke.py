"""Verify the pinned v4 harness against one cached real Verified task, offline.

Run in the existing harness image with its upstream Git clone; archive v4 into a
temporary directory so the original installation and all production state stay
unchanged. Mount /var/lib/ctxbench/datasets read-only at /datasets, this repo at
/source, and the Docker socket. The official reference patch stays grader-only.
"""
import importlib
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

import docker
import pyarrow.parquet as pq

PIN = "726c5461e2ef52d83cf1ea2107870a8bb3328d57"


def main():
    with tempfile.TemporaryDirectory(prefix="ctxbench-swe-v4-") as directory:
        root = Path(directory)
        source = root / "upstream"
        source.mkdir()
        archive = subprocess.check_output(["git", "-C", "/opt/swebench", "archive", PIN])
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            tar.extractall(source, filter="data")
        sys.path[:0] = [str(source), "/source/docker/official-harness"]
        harness = importlib.import_module("harness")
        importlib.import_module("policy").configure()
        rows = pq.read_table("/datasets/swebench-verified.parquet").to_pylist()
        client = docker.from_env()
        # A small known cached task; never silently pull another project's image.
        row = next(row for row in rows if row["instance_id"] == "sympy__sympy-12489")
        reference = "swebench/sweb.eval.x86_64.sympy_1776_sympy-12489:latest"
        image_id = client.images.get(reference).id
        original_pull = client.api.__class__.pull
        def no_pull(*_args, **_kwargs):
            raise AssertionError("Offline verification must reuse the installed image")
        client.api.__class__.pull = no_pull
        try:
            dataset = root / "dataset.json"
            dataset.write_text(json.dumps([row]))
            patch = root / "reference.patch"
            patch.write_text(row["patch"])
            output = root / "reference-grade"
            harness.grade_swebench(dataset, row["instance_id"], patch, output)
            summary = json.loads((output / "summary.json").read_text())
            result = json.loads(Path(summary["resultPath"]).read_text())
            assert row["instance_id"] not in result.get("error_ids", []), result.get("error_ids")
            assert summary["resolved"], "Official reference patch must resolve the cached task"
            assert client.images.get(reference).id == image_id
            print(json.dumps({"pin": PIN, "instance": row["instance_id"], "referenceResolved": True, "imagePreserved": image_id, "modelCalls": 0}))
        finally:
            client.api.__class__.pull = original_pull
            client.close()


if __name__ == "__main__":
    main()
