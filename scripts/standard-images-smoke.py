"""Run in an isolated worker container with Docker socket and this repo mounted.

Default: real local SWE/CTX image inspection and cache-only installation, no pulls.
--pull-smoke: also download Docker's tiny hello-world:linux transport fixture if
missing (not an official benchmark environment), then remove only its new tag.
No Agent or model is called; no production dataset/database is changed.
"""
import argparse
import json
import tempfile
from pathlib import Path

from worker.ctxbench_worker.engine import create_mock_engine
from worker.ctxbench_worker.intranet import IntranetWorkbench
from worker.ctxbench_worker.standard_images import DockerImages
from worker.ctxbench_worker.workbench import Workbench


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pull-smoke", action="store_true")
    args = parser.parse_args()
    fixtures = [
        ("ctxbench", {"instance_id": "opshin_opshin-fixture", "base_repo": "opshin/opshin", "base_sha": "3709012ef8c2bb33c18ce245bc9da400318630bd",
                      "problem_description": "Installation-only metadata fixture", "docker_image": "tgloaguen/planbenchx86_opshin_opshin:latest"}),
        ("swebench", {"instance_id": "sympy__sympy-12489", "repo": "sympy/sympy", "base_commit": "dce06f14c6c39c2a7883785b6b0798ed801c6e66",
                      "problem_statement": "Installation-only metadata fixture"}),
    ]
    with tempfile.TemporaryDirectory(prefix="ctxbench-image-install-") as directory:
        wb = Workbench(create_mock_engine(Path(directory)), None)
        op = IntranetWorkbench(wb)
        reports = []
        for benchmark, row in fixtures:
            dataset = wb.catalog.register("Image install fixture", benchmark, [row])["id"]
            plan = op.standard_images.plan(dataset)
            if not all(image["installed"] and image["compatible"] for image in plan["images"]):
                reports.append({"benchmark": benchmark, "skipped": "Required original image is not cached; default verification does not pull it."})
                continue
            operation = op.enqueue("standard-images", {"dataset": dataset, "taskIds": [row["instance_id"]], "confirmed": True})
            result = op.execute(operation)
            assert all(image["cached"] for image in result["images"])
            assert result["modelCalls"] == 0
            reports.append({"benchmark": benchmark, "result": result})
        if args.pull_smoke:
            reference = "hello-world:linux"
            with DockerImages() as store:
                present = store.inspect(reference)
                if present["installed"]:
                    reports.append({"transport": "skipped: hello-world:linux already present"})
                else:
                    events = []
                    try:
                        store.pull(reference, lambda: None, lambda text: (events.append(text), print(text, flush=True)))
                        downloaded = store.inspect(reference)
                        assert downloaded["installed"] and downloaded["compatible"]
                        assert events
                        reports.append({"transport": "real SDK pull passed", "imageId": downloaded["imageId"], "events": len(events)})
                    finally:
                        if store.inspect(reference)["installed"]:
                            store.client.images.remove(reference, noprune=True)
        print(json.dumps(reports, indent=2))


if __name__ == "__main__":
    main()
