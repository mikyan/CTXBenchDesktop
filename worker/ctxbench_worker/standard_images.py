"""Operator-only official image installation; never runs a container or a model."""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import time

from .environments import image_reference
from .preflight import storage_status


def swe_image(instance_id: str, *, solver: bool = False) -> str:
    instance = instance_id.replace("__", "_1776_").lower()
    owner = "tgloaguen" if solver and "matplotlib" in instance else "swebench"
    return image_reference(f"{owner}/sweb.eval.x86_64.{instance}:latest")


def project_image(task) -> str:
    if task.image:
        return image_reference(task.image)
    if task.source == "swebench":
        return swe_image(task.id, solver=True)
    raise ValueError("This task does not specify a project image. Import the complete official dataset.")


class DockerImages:
    """A killable SDK pull process keeps cancellation responsive even without events."""
    def __enter__(self):
        import docker
        self.client = docker.from_env(timeout=20)
        return self

    def __exit__(self, *_):
        self.client.close()

    def inspect(self, reference):
        import docker
        try:
            image = self.client.images.get(reference)
        except docker.errors.ImageNotFound:
            return {"installed": False, "imageId": None, "sizeBytes": None, "compatible": True}
        attrs = image.attrs
        return {"installed": True, "imageId": image.id, "sizeBytes": attrs.get("Size"),
                "compatible": attrs.get("Os") == "linux" and attrs.get("Architecture") == "amd64"}

    def pull(self, reference, check, progress):
        # The helper receives only a validated public image name, never Provider keys.
        transport_names = {"PATH", "PYTHONPATH", "HOME", "LANG", "TMPDIR", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE",
                           "DOCKER_HOST", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH", "DOCKER_CONFIG"}
        process = subprocess.Popen([sys.executable, "-u", "-m", __name__, "--pull", reference],
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                   env={key: value for key, value in os.environ.items() if key in transport_names})
        messages = queue.Queue(maxsize=128)
        done = threading.Event()

        def read():
            try:
                for line in process.stdout:
                    while not done.is_set():
                        try:
                            messages.put(line, timeout=.2)
                            break
                        except queue.Full:
                            pass
                    if done.is_set():
                        break
            finally:
                process.stdout.close()

        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        last_event = time.monotonic()
        try:
            while process.poll() is None or reader.is_alive() or not messages.empty():
                check()
                try:
                    message = messages.get(timeout=.5)
                except queue.Empty:
                    if time.monotonic() - last_event >= 10:
                        progress("Waiting for registry or layer extraction; cancellation remains available.")
                        last_event = time.monotonic()
                    continue
                progress(message.rstrip()[:2000])
                last_event = time.monotonic()
            if process.wait() != 0:
                raise ValueError("Image download failed. Check the last layer message, Docker registry access, disk space and registry login in WSL; retry reuses completed images. Provider API keys do not authenticate Docker registries.")
        finally:
            done.set()
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
            reader.join(timeout=1)


class StandardImages:
    def __init__(self, operator, store=DockerImages):
        self.operator, self.wb, self.store = operator, operator.wb, store

    def requirements(self, dataset, task_ids=None):
        record = self.wb.catalog.verify(dataset)
        if record["benchmark"] not in {"ctxbench", "swebench"}:
            raise ValueError("Select an imported CTXBench or SWE-bench dataset.")
        index = self.wb.catalog.index(dataset)
        if task_ids is None:
            task_ids = list(index)
        if (not isinstance(task_ids, list) or not 1 <= len(task_ids) <= 10000
                or not all(isinstance(key, str) for key in task_ids)
                or len(task_ids) != len(set(task_ids)) or any(key not in index for key in task_ids)):
            raise ValueError("Select unique tasks from this imported dataset.")
        tasks, references = [], {}
        for key in task_ids:
            task = index[key]
            needed = [project_image(task)]
            # v4 official grading uses the swebench namespace; the upstream CTX
            # solver uses a rootless-compatible matplotlib variant as well.
            if task.source == "swebench":
                needed.append(swe_image(task.id))
            needed = list(dict.fromkeys(needed))
            for reference in needed:
                self.operator.material(reference)
                references.setdefault(reference, []).append(key)
            tasks.append({"id": key, "repository": task.repository, "images": needed})
        return record, tasks, references

    def plan(self, dataset):
        record, tasks, references = self.requirements(dataset)
        with self.store() as store:
            images = [{"reference": ref, "taskIds": ids, **store.inspect(ref)} for ref, ids in references.items()]
        operations = [self.operator.status(op["id"]) for op in self.wb.db.list_documents("operations")
                      if op["kind"] == "intranet:standard-images" and op["payload"].get("dataset") == dataset]
        return {"dataset": dataset, "benchmark": record["benchmark"], "tasks": tasks, "images": images,
                "storage": storage_status(self.wb.root), "operations": operations[-10:]}

    def validate(self, payload):
        if set(payload) != {"dataset", "taskIds", "confirmed"} or payload.get("confirmed") is not True:
            raise ValueError("Confirm the selected project image downloads and disk-space warning first.")
        self.requirements(payload["dataset"], payload["taskIds"])

    def install(self, operation):
        self.validate(operation["payload"])
        _, tasks, references = self.requirements(operation["payload"]["dataset"], operation["payload"]["taskIds"])
        images = []
        with self.store() as store:
            for index, reference in enumerate(references):
                self.wb._check(None)
                percent = int(index / len(references) * 100)
                emit = lambda message: self.operator.progress(operation, message, percent)
                emit(f"Image {index + 1}/{len(references)}: {reference}")
                local = store.inspect(reference)
                if local["installed"] and not local["compatible"]:
                    raise ValueError(f"Local image has the wrong platform (requires linux/amd64): {reference}. Remove or retag that conflicting image explicitly before retrying; it has not been overwritten.")
                cached = local["installed"]
                if not cached:
                    store.pull(reference, lambda: self.wb._check(None), emit)
                    local = store.inspect(reference)
                self.wb._check(None)
                if not local["installed"] or not local["compatible"]:
                    raise ValueError("Image download finished without a matching linux/amd64 local image.")
                emit("Already installed; reused without contacting the registry." if cached else "Image downloaded and inspected.")
                images.append({"reference": reference, **local, "cached": cached})
                self.operator.progress(operation, f"Available images: {index + 1}/{len(references)}", int((index + 1) / len(references) * 100))
        return {"dataset": operation["payload"]["dataset"], "taskCount": len(tasks), "images": images,
                "scope": "project-images-only", "modelCalls": 0}


if __name__ == "__main__":
    import docker
    if len(sys.argv) != 3 or sys.argv[1] != "--pull":
        raise SystemExit(2)
    reference = image_reference(sys.argv[2])
    client = docker.from_env(timeout=60)
    try:
        last_progress = 0
        for event in client.api.pull(reference, stream=True, decode=True, platform="linux/amd64"):
            # Never dump whole events, headers or registry auth configuration.
            now = time.monotonic()
            if event.get("progress") and not event.get("error") and now - last_progress < .25:
                continue
            last_progress = now
            print(" ".join(str(event.get(key, "")) for key in ("id", "status", "progress", "error")).strip(), flush=True)
            if event.get("error"):
                raise SystemExit(1)
    except docker.errors.DockerException:
        print("Docker registry connection failed or timed out.", flush=True)
        raise SystemExit(1)
    finally:
        client.close()
