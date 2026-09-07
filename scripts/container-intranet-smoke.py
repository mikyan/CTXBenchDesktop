"""No-model acceptance: adapt -> self-test -> export -> clean Worker import -> self-test.

Run in a test container with the Docker socket and CTXBENCH_SMOKE_ROOT mounted at
the identical absolute host/container path. Only UUID-owned resources are removed.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import uuid
from pathlib import Path

import docker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from worker.ctxbench_worker.artifacts import ArtifactStore, ContextIdentity
from worker.ctxbench_worker.database import Database
from worker.ctxbench_worker.engine import ExperimentEngine
from worker.ctxbench_worker.intranet import IntranetWorkbench
from worker.ctxbench_worker.models import ModelConfig
from worker.ctxbench_worker.portable import PortableResources, source_key
from worker.ctxbench_worker.runner import DockerRunner
from worker.ctxbench_worker.runtime import git, seal
from worker.ctxbench_worker.workbench import Workbench


def service(root):
    root.mkdir(parents=True)
    runner = DockerRunner(root / "repositories", root / "artifacts", root / "requests", worker_data_root=root, host_data_root=str(root))
    engine = ExperimentEngine(Database(root / "ctxbench.sqlite3"), ArtifactStore(root / "artifacts"), runner)
    return IntranetWorkbench(Workbench(engine, None))


def execute(tools, kind, payload):
    operation = tools.enqueue(kind, payload)
    result = tools.execute(operation)
    operation.update(status="completed", result=result)
    tools.db.put_document("operations", operation["id"], operation)
    return result


def main():
    parent = Path(os.environ["CTXBENCH_SMOKE_ROOT"]).resolve()
    if not parent.is_dir() or not parent.name.startswith("ctxbench-intranet-smoke-") or not parent.is_absolute():
        raise SystemExit("Use an explicitly mounted, UUID-owned ctxbench-intranet-smoke-* directory.")
    root = Path(tempfile.mkdtemp(prefix="acceptance-", dir=parent))
    client = docker.from_env(timeout=3600)
    owned_image = None
    base_ref = os.environ.get("CTXBENCH_SMOKE_BASE_IMAGE", "ctxbench/worker:args-tests-20260907")
    base_before = client.images.get(base_ref).id
    try:
        source = root / "source"
        source.mkdir()
        (source / "README.md").write_text("Synthetic repository for intranet smoke test.\n")
        parent_commit = seal(source)
        (source / "arithmetic.py").write_text("def add(left, right):\n    return left - right\n")
        (source / "test_existing.py").write_text("import unittest\nfrom arithmetic import add\nclass Existing(unittest.TestCase):\n    def test_zero(self):\n        self.assertEqual(add(0, 0), 0)\n")
        commit = seal(source)
        (source / "arithmetic.py").write_text("def add(left, right):\n    return left + right\n")
        gold = git(source, "diff", "--binary", commit).decode()
        (source / "arithmetic.py").write_text("def add(left, right):\n    return left - right\n")
        (source / "future-private-answer.txt").write_text("FUTURE_EVALUATOR_DATA_MUST_NOT_TRAVEL")
        git(source, "add", "--all")
        git(source, "commit", "-qm", "Future excluded history")
        future = git(source, "rev-parse", "HEAD").decode().strip()
        first = service(root / "first-worker")
        receipt = execute(first, "image-build", {"name": "Isolated intranet acceptance", "baseImage": base_ref,
            "dockerfile": "RUN mkdir -p /opt/company && printf '%s' '" + uuid.uuid4().hex + "' > /opt/company/adaptation-proof\n",
            "files": [], "network": "none"})
        owned_image = receipt["imageId"]
        assert owned_image != base_before
        print("PASS: independent image adaptation, pinned base and unique output tag", flush=True)
        hidden = "diff --git a/test_hidden.py b/test_hidden.py\nnew file mode 100644\n--- /dev/null\n+++ b/test_hidden.py\n@@ -0,0 +1,5 @@\n+import unittest\n+from arithmetic import add\n+class Hidden(unittest.TestCase):\n+    def test_addition(self):\n+        self.assertEqual(add(2, 3), 5)\n"
        row = {"id": "addition", "repository": str(source), "baseCommit": commit, "prompt": "Correct addition behavior.",
               "image": receipt["tag"], "test": {"command": ["python", "-m", "unittest", "discover", "-v"], "hiddenPatch": hidden}, "goldPatch": gold}
        dataset = first.wb.catalog.register("Intranet acceptance", "custom", [row])
        before = execute(first, "probe", {"name": "Self-test", "rows": [row]})
        assert before["reports"][0]["candidateReady"], before
        assert before["agentInvocations"] == 0
        print("PASS: existing tests pass; baseline hidden test fails; reference fix passes", flush=True)
        identity = ContextIdentity(str(source), commit, "tree-only", "manual", "manual", ModelConfig("mock", "no-model-call", "off", 1))
        first.wb.engine.artifacts.publish(identity, {"AGENTS.md": b"Arithmetic helpers are in arithmetic.py.\n"}, {"source": "manual", "createdAt": "2026-09-07"})
        bundle = execute(first, "bundle-export", {"dataset": dataset["id"], "images": [], "contextIds": [identity.key()], "profileIds": []})
        print("PASS: resource export with exact baseline, image and frozen context", flush=True)
        second = service(root / "second-worker")
        transfer = PortableResources(second)
        shutil.copyfile(bundle["path"], transfer.root / bundle["filename"])
        # Delete only this test's uniquely built image, to force an actual docker load.
        client.images.remove(owned_image, force=True)
        result = execute(second, "bundle-import", {"filename": bundle["filename"], "expectedSha256": bundle["sha256"], "trusted": True})
        assert result["datasetId"] == dataset["id"]
        assert second.wb.engine.artifacts.verify(identity.key()) == first.wb.engine.artifacts.verify(identity.key())
        imported = second.wb.root / "sources" / source_key(str(source), commit)
        for excluded in (future, parent_commit):
            try:
                git(imported, "cat-file", "-e", excluded)
                raise AssertionError("History leaked into portable baseline")
            except RuntimeError:
                pass
        task = second.wb.catalog.task(dataset["id"], "addition")
        # Disable all baseline/image fetches on the destination. Remove the source repo
        # from its original location so accidental use of the old cache cannot pass.
        source.rename(root / "source-disconnected")
        with second.runtime.using_environment({"offline": True}):
            workspace = second.runtime.checkout(task, "acceptance-solver-input")
            assert not (workspace / "future-private-answer.txt").exists()
            assert not (workspace / "test_hidden.py").exists()
        after = second.enqueue("probe", {"name": "After migration", "rows": [row]})
        after["payload"]["environment"] = {"offline": True}
        checked = second.execute(after)
        assert checked["reports"][0]["candidateReady"], checked
        assert client.images.get(base_ref).id == base_before
        print("PASS: clean Worker import, real image load, offline baseline checkout and repeated self-test", flush=True)
        print(json.dumps({"passed": True, "agentInvocations": 0, "officialSuitesIncluded": False, "existingBaseImageUnchanged": True}), flush=True)
    finally:
        if owned_image and owned_image != base_before:
            try:
                client.images.remove(owned_image, force=True)
            except docker.errors.ImageNotFound:
                pass
        client.close()
        if root.resolve().parent == parent and root.name.startswith("acceptance-"):
            shutil.rmtree(root)


if __name__ == "__main__":
    main()
