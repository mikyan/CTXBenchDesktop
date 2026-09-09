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
from .image_sources import ImageSources
from .catalog import fingerprint
from .database import utc_now


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

    def availability(self, reference):
        import docker
        import requests
        try:
            data = self.client.images.get_registry_data(reference)
            return 'available' if data.has_platform('linux/amd64') else 'wrong-platform'
        except docker.errors.APIError as error:
            # The daemon sometimes wraps registry HTTP errors in its own 500.
            # Classify known responses but never return raw server bodies/auth.
            message = str(error).lower()
            status = getattr(error, 'status_code', None)
            if status in {401, 403} or any(word in message for word in ('unauthorized', 'authentication required', 'denied', 'forbidden')):
                return 'auth-required'
            if status == 404 or any(word in message for word in ('manifest unknown', 'name unknown')):
                return 'not-found'
            return 'unreachable'
        except (docker.errors.DockerException, requests.exceptions.RequestException):
            return 'unreachable'

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
                raise ValueError("Image download failed. Check registry access and disk space. For private registries, pull the displayed image with docker login / docker pull in the selected WSL distribution, then refresh here. Host Docker credentials are not automatically shared with the evaluation service. Provider API keys do not authenticate Docker registries.")
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
        record = self.wb.library.definition(dataset) if self.wb.library.editable(dataset) else self.wb.catalog.verify(dataset)
        if record["benchmark"] not in {"ctxbench", "swebench"}:
            raise ValueError("Select an imported CTXBench or SWE-bench dataset.")
        from .datasets import TaskRecord
        index = {task['id']: TaskRecord(**{**task, 'test_command': tuple(task['test_command'])}) for task in record['tasks']}
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

    def resolved_requirements(self, dataset, task_ids=None):
        record, tasks, references = self.requirements(dataset, task_ids)
        sources = ImageSources(self.wb.runtime.environment)
        mapped = {}
        for original, ids in references.items():
            ref = sources.resolve(original)
            item = mapped.setdefault(ref, {'reference': ref, 'taskIds': [], 'originals': [], 'pullAllowed': sources.may_pull(original)})
            item['taskIds'] = list(dict.fromkeys(item['taskIds'] + ids))
            item['originals'].append(original)
        return record, [{**task, 'images': list(dict.fromkeys(sources.resolve(ref) for ref in task['images']))} for task in tasks], mapped

    def check_key(self, reference):
        return fingerprint({'environment': self.wb.runtime.environment, 'reference': reference})

    def plan(self, dataset, environment=None):
        environment = self.wb.runtime.environment if environment is None else environment
        settings = self.wb.image_sources.view(dataset, environment)
        frozen = self.wb.image_sources.freeze(dataset, environment=environment, expected_revision=settings['revision'])
        with self.wb.runtime.using_environment(frozen):
            return {**self._plan(dataset, self.wb.image_sources.scope(environment)),
                    'imageSources': settings}

    def _plan(self, dataset, profile_id):
        record, tasks, references = self.resolved_requirements(dataset)
        with self.store() as store:
            images = []
            for ref, item in references.items():
                try:
                    remote = self.wb.db.get_document('imageAvailability', self.check_key(ref))
                except KeyError:
                    remote = {'status': 'unchecked'}
                images.append({**item, **store.inspect(ref), 'remote': remote})
        operations = [self.operator.status(op["id"]) for op in self.wb.db.list_documents("operations")
                      if op["kind"] in {"intranet:standard-images", "intranet:image-check"} and op["payload"].get('sourceDataset', op['payload'].get('dataset')) == dataset
                      and op['payload'].get('profileId', '') == profile_id]
        return {"dataset": dataset, 'datasetRevision': record.get('contentRevision', dataset), "benchmark": record["benchmark"], "tasks": tasks, "images": images,
                "storage": storage_status(self.wb.root), "operations": operations[-10:]}

    def validate(self, payload):
        if not {'dataset', 'taskIds', 'confirmed'} <= set(payload) or set(payload) - {'dataset', 'taskIds', 'confirmed', 'profileId', 'datasetRevision', 'imageSourcesRevision'} or payload.get("confirmed") is not True:
            raise ValueError("Confirm the selected project image downloads and disk-space warning first.")
        self.requirements(payload["dataset"], payload["taskIds"])

    def install(self, operation):
        self.validate({key: value for key, value in operation['payload'].items()
                       if key not in {'environment', 'sourceDataset', 'datasetSnapshot'}})
        _, tasks, references = self.resolved_requirements(operation["payload"]["dataset"], operation["payload"]["taskIds"])
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
                    if not references[reference]['pullAllowed']:
                        raise ValueError(f'No permitted registry mapping for missing image: {reference}. Add a mapping or import it locally. No public registry fallback was attempted.')
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

    def check(self, operation):
        """Explicit, cancellable metadata-only check; a 404 never changes a dataset."""
        self.validate({key: value for key, value in operation['payload'].items()
                       if key not in {'environment', 'sourceDataset', 'datasetSnapshot'}})
        _, tasks, references = self.resolved_requirements(operation['payload']['dataset'], operation['payload']['taskIds'])
        results = []
        with self.store() as store:
            for index, (ref, item) in enumerate(references.items()):
                self.wb._check(None)
                self.operator.progress(operation, f'Checking image {index + 1}/{len(references)}: {ref}', int(index / len(references) * 100))
                local = store.inspect(ref)
                if local['installed']:
                    status = 'local' if local['compatible'] else 'wrong-platform'
                else:
                    status = store.availability(ref) if item['pullAllowed'] else 'unmapped'
                self.wb._check(None)
                receipt = {'id': self.check_key(ref), 'reference': ref, 'status': status, 'checkedAt': utc_now()}
                self.wb.db.put_document('imageAvailability', receipt['id'], receipt)
                results.append(receipt)
                self.operator.progress(operation, f'{status}: {ref}', int((index + 1) / len(references) * 100))
        return {'dataset': operation['payload']['dataset'], 'taskCount': len(tasks), 'images': results, 'modelCalls': 0,
                'scope': 'image-availability-only'}


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
