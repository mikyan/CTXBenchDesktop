"""Operator-only tools, serialized with experiments by the durable workbench queue."""
from __future__ import annotations

import base64
import io
import json
import re
import shutil
import tarfile
import uuid
from dataclasses import replace
from pathlib import Path

from .artifacts import safe_relative_path
from .catalog import fingerprint
from .database import utc_now
from .environments import EnvironmentProfiles, image_reference, public_material, public_image_config
from .models import ResourcePolicy
from .runner import DockerRunner


class IntranetWorkbench:
    def __init__(self, workbench):
        self.wb = workbench
        self.db, self.runtime = workbench.db, workbench.runtime
        self.root = workbench.root / "intranet"
        self.root.mkdir(parents=True, exist_ok=True)
        self.profiles = EnvironmentProfiles(self.db, workbench.redact)
        from .standard_images import StandardImages
        self.standard_images = StandardImages(self)
        for kind in ("probe", "image-build", "image-pull", "bundle-export", "bundle-import", "bundle-inspect", "standard-images", "image-check"):
            workbench.operation_handlers["intranet:" + kind] = self.execute

    def material(self, value):
        public_material(value, self.wb.redact)

    def material_bytes(self, data):
        # Binary installers/certificates legitimately contain NULs. Also scan
        # UTF-16-style ASCII secrets without retaining decoded binary content.
        self.material(data.replace(b"\0", b"").decode("utf-8", errors="replace"))

    def cancel_interrupted_graders(self):
        if isinstance(self.wb.engine.runner, DockerRunner):
            for record in self.db.list_documents("intranetGrades"):
                if record["status"] == "running":
                    self.runtime.cancel_grade(Path(record["output"]))
                    record["status"] = "interrupted"
                    self.db.put_document("intranetGrades", record["id"], record)

    def enqueue(self, kind, payload):
        if kind not in {"probe", "image-build", "image-pull", "bundle-export", "bundle-import", "bundle-inspect", "standard-images", "image-check"}:
            raise ValueError("Unknown intranet operation.")
        self.material(payload)
        allowed = {
            'image-pull': {'image', 'confirmed'},
            "probe": {"name", "benchmark", "rows", "profileId"},
            "image-build": {"name", "baseImage", "dockerfile", "files", "network", "profileId"},
            "bundle-export": {"dataset", "images", "contextIds", "profileIds", "profileId", "datasetRevision"},
            "bundle-import": {"filename", "expectedSha256", "trusted"},
            "bundle-inspect": {"filename"},
            "standard-images": {"dataset", "taskIds", "confirmed", "profileId", "datasetRevision", "imageSourcesRevision"},
            "image-check": {"dataset", "taskIds", "confirmed", "profileId", "datasetRevision", "imageSourcesRevision"},
        }
        if not isinstance(payload, dict) or set(payload) - allowed[kind]:
            raise ValueError("Unsupported operator operation fields.")
        if kind == 'image-pull':
            image_reference(payload.get('image'))
            if payload.get('confirmed') is not True or payload['image'].startswith('sha256:'):
                raise ValueError('Confirm a remote repository:tag or repository@sha256:digest to download.')
        if kind in {"standard-images", "image-check"}:
            self.standard_images.validate(payload)
            if any(op["kind"] in {"intranet:standard-images", "intranet:image-check"} and op["status"] in {"queued", "running", "paused"}
                   and op['payload'].get('sourceDataset', op['payload'].get('dataset')) == payload['dataset'] for op in self.db.list_documents("operations")):
                raise ValueError("An image installation for this dataset is already queued, running or paused. Open its progress to cancel or resume it.")
        if kind == "probe":
            tasks = self.wb.catalog.validate(payload.get("name"), "custom", payload.get("rows"))
            if any(task.ci for task in tasks):
                raise ValueError('CI: the local self-test never uploads code. Run CI cases through an explicitly configured experiment.')
            if len(tasks) > 20:
                raise ValueError("Self-test at most 20 tasks at a time.")
            if not all(task.gold_patch for task in tasks):
                raise ValueError("Every self-test task needs an evaluator-only reference fix (goldPatch).")
        if kind == "image-build":
            payload = self.recipe(payload)
            for file in payload["files"]:
                self.material_bytes(base64.b64decode(file["base64"], validate=True))
        if kind == "bundle-export":
            dataset = self.wb.library.definition(payload.get('dataset', ''))
            if dataset["benchmark"] != "custom":
                raise ValueError("Portable v1 supports custom prebuilt-image datasets only.")
            for key in ("images", "contextIds", "profileIds"):
                items = payload.get(key, [])
                if not isinstance(items, list) or len(items) > 100 or not all(isinstance(i, str) for i in items) or len(items) != len(set(items)):
                    raise ValueError("Provide unique resource IDs (at most 100 of each kind).")
        if kind in {'standard-images', 'image-check', 'bundle-export'} and self.wb.library.editable(payload.get('dataset')):
            source = payload['dataset']
            dataset, receipt = self.wb.library.freeze(source, payload.get('taskIds'), payload.get('datasetRevision'))
            payload = {**payload, 'dataset': dataset, 'sourceDataset': source, 'datasetSnapshot': receipt}
        if kind == 'probe':
            frozen = self.wb.catalog.register(payload['name'], 'custom', payload['rows'], internal=True)
            payload = {**payload, 'definitionSnapshot': frozen['id']}
        if payload.get("profileId"):
            # Queue the snapshot, not a mutable pointer to environment settings.
            payload = {**payload, "environment": self.profiles.get(payload["profileId"])}
        if kind in {'standard-images', 'image-check'}:
            environment = self.wb.image_sources.freeze(payload['dataset'], payload['taskIds'], payload.get('environment'), payload.get('imageSourcesRevision'))
            if environment:
                payload = {**payload, 'environment': environment}
        return self.wb.enqueue("intranet:" + kind, payload)

    def progress(self, operation, message, percent=None):
        from .diagnostics import note
        note(message)
        key = operation["id"]
        try:
            current = self.db.get_document("intranetProgress", key)
        except KeyError:
            current = {"id": key, "log": ""}
        current.update(log=(current["log"] + self.wb.redact(str(message)) + "\n")[-48000:], updatedAt=utc_now())
        if percent is not None:
            current["percent"] = percent
        self.db.put_document("intranetProgress", key, current)

    def status(self, key):
        operation = self.db.get_document("operations", key)
        if not operation["kind"].startswith("intranet:"):
            raise ValueError("Not an intranet operation.")
        result = {k: operation[k] for k in ("id", "kind", "status", "createdAt", "updatedAt", "failure", "result", "diagnostic") if k in operation}
        result['datasetSnapshot'] = operation['payload'].get('datasetSnapshot')
        result['definitionSnapshot'] = operation['payload'].get('definitionSnapshot')
        try:
            result["progress"] = self.db.get_document("intranetProgress", key)
        except KeyError:
            pass
        return result

    def execute(self, operation):
        self.wb._check(None)
        # Interrupted builds/imports require explicit retry, never silent replay on restart.
        attempt = self.root / "jobs" / (operation["id"] + "-" + uuid.uuid4().hex[:8])
        attempt.mkdir(parents=True)
        self.progress(operation, "Starting isolated operator workspace.", 0)
        try:
            with self.runtime.using_environment(operation["payload"].get("environment", {})):
                kind = operation["kind"].split(":")[1]
                if kind == "probe":
                    result = self.probe(operation, attempt)
                elif kind == "image-build":
                    result = self.build(operation, attempt)
                elif kind == 'image-pull':
                    result = self.pull(operation)
                elif kind == "standard-images":
                    result = self.standard_images.install(operation)
                elif kind == "image-check":
                    result = self.standard_images.check(operation)
                else:
                    from .portable import PortableResources
                    bundles = PortableResources(self)
                    if kind == "bundle-inspect":
                        result = {"inspection": bundles.inspect(operation["payload"]["filename"], lambda message, percent: self.progress(operation, message, percent))}
                    else:
                        result = (bundles.export(operation, attempt) if kind == "bundle-export" else bundles.import_bundle(operation, attempt))
        finally:
            # Only this freshly-created staging directory; retained results are in
            # the database/transfers. Never remove the operator's input archive.
            if attempt.resolve().parent == (self.root / "jobs").resolve() and not attempt.is_symlink():
                shutil.rmtree(attempt)
        self.progress(operation, "Completed. No model tokens used.", 100)
        return result

    @staticmethod
    def recipe(value):
        if not isinstance(value, dict) or set(value) - {"name", "baseImage", "dockerfile", "files", "network", "profileId"}:
            raise ValueError("Unsupported image recipe fields.")
        image_reference(value.get("baseImage"))
        if value.get("network") not in {"none", "bridge"}:
            raise ValueError("Choose offline or network-enabled build explicitly.")
        if not isinstance(value.get("name"), str) or not 1 <= len(value["name"]) <= 120:
            raise ValueError("Give the image adaptation a name.")
        recipe = value.get("dockerfile")
        if not isinstance(recipe, str) or not recipe.strip() or len(recipe) > 100_000 or re.search(r"^\s*(FROM|ARG)\b|^#\s*syntax=", recipe, re.I | re.M):
            raise ValueError("Enter Dockerfile instructions after FROM; base image is pinned automatically. ARG and remote syntax frontends are not supported.")
        if re.search(r"^\s*ENV\b[^\n]*(?:API[_-]?KEY|PASSWORD|TOKEN|SECRET|PRIVATE_KEY|ACCESS_KEY)", recipe, re.I | re.M):
            raise ValueError("Do not define credential environment variables in an image recipe. Pass them at Agent runtime only.")
        files = value.get("files", [])
        if not isinstance(files, list) or len(files) > 200:
            raise ValueError("Include at most 200 local adaptation files.")
        seen, total = set(), 0
        for file in files:
            if not isinstance(file, dict) or set(file) != {"path", "base64"}:
                raise ValueError("Each build file needs path and base64 contents.")
            path = safe_relative_path(file["path"]).as_posix()
            if path != file["path"] or path in seen or path.lower() in {"dockerfile", ".dockerignore"} or re.search(r"(?i)(^|/)(\.env(?:\..*)?|id_rsa|id_ed25519|auth\.json|credentials|\.npmrc|\.pypirc)$", path):
                raise ValueError("Duplicate, reserved or credential-bearing build filename.")
            try:
                content = base64.b64decode(file["base64"], validate=True)
            except (ValueError, TypeError) as error:
                raise ValueError("Invalid build file encoding.") from error
            total += len(content)
            if total > 30 * 1024 * 1024:
                raise ValueError("Uploaded build files exceed 30 MiB. Put large installers in a pre-adapted base image.")
            seen.add(path)
        if any(any(parent.as_posix() in seen for parent in Path(path).parents) for path in seen):
            raise ValueError("A build file cannot be another file's parent directory.")
        return {**value, "files": files}

    def pull(self, operation):
        from .standard_images import DockerImages
        from .preflight import storage_status
        if not isinstance(self.wb.engine.runner, DockerRunner):
            raise ValueError('Image downloads require the Docker worker.')
        if not storage_status(self.wb.root)['ready']:
            raise ValueError('Free disk space before downloading images.')
        reference = operation['payload']['image']
        with DockerImages() as images:
            present = images.inspect(reference)
            if present['installed'] and not present['compatible']:
                raise ValueError('Existing image is not Linux amd64; choose another tag. It was not replaced.')
            if not present['installed']:
                self.progress(operation, 'Downloading ' + reference + '. Layer byte progress follows; extraction has no reliable percentage.')
                images.pull(reference, lambda: self.wb._check(None), lambda message: self.progress(operation, message))
            result = images.inspect(reference)
            if not result['installed'] or not result['compatible']:
                raise ValueError('The downloaded image is not a usable Linux amd64 image.')
            self.progress(operation, 'Cached image reused.' if present['installed'] else 'Download verified.')
            return {**result, 'tag': reference, 'cached': present['installed'], 'modelCalls': 0}

    def build(self, operation, attempt):
        import docker
        value = operation["payload"]
        client = docker.from_env(timeout=3600)
        tag = "ctxbench/adapted:" + uuid.uuid4().hex
        try:
            base = client.images.get(value["baseImage"])
            public_image_config(base.attrs.get("Config", {}), self.wb.redact)
            dockerfile = "FROM " + base.id + "\n" + value["dockerfile"] + "\n"
            self.material(dockerfile)
            archive = io.BytesIO()
            with tarfile.open(fileobj=archive, mode="w") as tar:
                for name, data in [("Dockerfile", dockerfile.encode()), *[(f["path"], base64.b64decode(f["base64"], validate=True)) for f in value["files"]]]:
                    self.material_bytes(data)
                    info = tarfile.TarInfo(name)
                    info.size, info.mode = len(data), 0o644
                    tar.addfile(info, io.BytesIO(data))
            archive.seek(0)
            self.progress(operation, f"Base pinned: {base.id}. Build output follows (Docker does not report a reliable percentage).", 10)
            for event in client.api.build(fileobj=archive, custom_context=True, tag=tag, rm=True, forcerm=True,
                                          pull=False, network_mode=value["network"], decode=True):
                self.wb._check(None)
                if event.get("stream"):
                    self.progress(operation, event["stream"].rstrip())
                if event.get("error"):
                    raise ValueError(self.wb.redact(event["error"]))
            built = client.images.get(tag)
            public_image_config(built.attrs.get("Config", {}), self.wb.redact)
            config = built.attrs.get("Config", {})
            record = {"id": fingerprint({"image": built.id, "recipe": value}), "name": value["name"],
                      "createdAt": utc_now(), "baseImageId": base.id, "imageId": built.id, "tag": tag,
                      "recipe": value, "entrypoint": config.get("Entrypoint"), "user": config.get("User"),
                      "labels": {k: v for k, v in (config.get("Labels") or {}).items() if k.startswith("io.ctxbench.")},
                      "protocolTested": False}
            self.db.put_document("imageAdaptations", record["id"], record)
            self.progress(operation, "Image built; compatibility labels are informational, not an Agent protocol test.", 95)
            return record
        finally:
            client.close()

    def probe(self, operation, attempt):
        if not isinstance(self.wb.engine.runner, DockerRunner):
            raise ValueError("Dataset self-test requires the Docker worker. Mock execution cannot validate tests.")
        value = operation["payload"]
        tasks = self.wb.catalog.validate(value["name"], "custom", value["rows"])
        reports = []
        resources = ResourcePolicy(cpus=2, memory_gb=4, timeout_minutes=10, network="offline")
        for index, original in enumerate(tasks):
            self.wb._check(None)
            self.progress(operation, f"Preparing task {original.id} ({index + 1}/{len(tasks)}).", int(index / len(tasks) * 95))
            phases = {}
            try:
                task = replace(original, image=self.runtime.prepare_test_image(original))
                tests = [("baseline", task, ""), ("reference", task, task.gold_patch)]
                if task.hidden_test_patch:
                    tests = [("existing-baseline", replace(task, hidden_test_patch=None), ""),
                             ("existing-reference", replace(task, hidden_test_patch=None), task.gold_patch)] + tests
                for phase, checked_task, patch_text in tests:
                    self.wb._check(None)
                    path = attempt / str(index) / phase
                    path.mkdir(parents=True)
                    patch = path / "candidate.patch"
                    patch.write_text(patch_text or "", encoding="utf-8")
                    grade_key = f"{operation['id']}:{index}:{phase}"
                    grade_record = {"id": grade_key, "output": str(path), "status": "running"}
                    self.db.put_document("intranetGrades", grade_key, grade_record)
                    try:
                        summary = self.runtime.grade(checked_task, path / "unused.json", patch, path, resources, "custom")
                    finally:
                        grade_record["status"] = "finished"
                        self.db.put_document("intranetGrades", grade_key, grade_record)
                    log_path = path / "evaluator.log"
                    log = self.wb.redact(log_path.read_text(encoding="utf-8", errors="replace")) if log_path.exists() else ""
                    # Graders have no credential env. Redact additionally before retaining their diagnostics.
                    if log_path.exists():
                        log_path.write_text(log, encoding="utf-8")
                    infrastructure = summary.get("exitCode") in {125, 126, 127, 137} or bool(re.search(
                        r"ModuleNotFoundError|command not found|No such file or directory|Cannot find module|ERROR collecting|ImportError", log))
                    phases[phase] = {**summary, "infrastructureError": infrastructure, "log": log[-16000:]}
                    self.progress(operation, f"{original.id} / {phase}: exit {summary.get('exitCode')}")
                ready = (phases["baseline"].get("exitCode") == 1 and phases["reference"].get("resolved") is True
                         and not any(p["infrastructureError"] for p in phases.values())
                         and all(p["resolved"] for name, p in phases.items() if name.startswith("existing-")))
                reports.append({"taskId": original.id, "imageId": task.image, "candidateReady": ready, "phases": phases,
                                "reviewRequired": "Inspect the baseline failure: an exit code alone cannot prove a behavioral regression."})
            except Exception as error:
                # Cancellation is cooperative between phases, not a model/test failure.
                self.wb._check(None)
                reports.append({"taskId": original.id, "candidateReady": False, "phases": phases,
                                "failure": self.wb.redact(str(error)), "infrastructureError": True})
        result = {"id": fingerprint(value), "testsExecuted": True, "agentInvocations": 0, "reports": reports}
        self.db.put_document("datasetSelfTests", operation["id"], result)
        return result

    def save_draft(self, value):
        self.material(value)
        if not isinstance(value, dict) or value.get("format") != "ctxbench-dataset-draft" or value.get("version") != 1 or not isinstance(value.get("tasks"), list) or len(json.dumps(value)) > 10_000_000:
            raise ValueError("Unsupported or oversized dataset draft.")
        record = {"id": fingerprint(value), "name": str(value.get("name", ""))[:160], "createdAt": utc_now(), "document": value}
        self.db.put_document("datasetDrafts", record["id"], record)
        return record


def register_intranet_routes(app, service):
    @app.get("/v1/intranet")
    def inventory():
        transfer = service.root / "transfers"
        transfer.mkdir(parents=True, exist_ok=True)
        return {"profiles": service.profiles.list(), "adaptations": service.db.list_document_summaries("imageAdaptations", ("id", "name", "imageId", "tag", "createdAt", "protocolTested")),
                "drafts": service.db.list_document_summaries("datasetDrafts", ("id", "name", "createdAt")),
                "operations": [service.status(o["id"]) for o in service.db.list_documents("operations") if o["kind"].startswith("intranet:")][-30:],
                "transferDirectory": str(transfer), "hostTransferDirectory": service.runtime.host_path(transfer) if isinstance(service.wb.engine.runner, DockerRunner) else None}

    @app.get("/v1/intranet/profiles")
    def profiles():
        return service.profiles.list()

    @app.get("/v1/datasets/{key}/project-images")
    def standard_image_plan(key: str, profileId: str = ''):
        return service.standard_images.plan(key, service.profiles.get(profileId) if profileId else {})

    @app.get('/v1/datasets/{key}/project-image-sources')
    def project_image_sources(key: str, profileId: str = ''):
        return service.wb.image_sources.view(key, service.profiles.get(profileId) if profileId else {})

    @app.put('/v1/datasets/{key}/project-image-sources')
    def save_project_image_sources(key: str, value: dict):
        environment = service.profiles.get(value['profileId']) if value.get('profileId') else {}
        return service.wb.image_sources.save(key, value, environment)

    @app.get("/v1/intranet/images/{key}")
    def image_recipe(key: str):
        return service.db.get_document("imageAdaptations", key)

    @app.post("/v1/intranet/profiles")
    def save_profile(value: dict):
        return service.profiles.save(value)

    @app.get("/v1/intranet/profiles/{key}/proxy")
    def proxy(key: str):
        return {"filename": "squid.conf", "content": service.profiles.proxy_config(key)}

    @app.post("/v1/intranet/drafts")
    def save_draft(value: dict):
        return service.save_draft(value)

    @app.get("/v1/intranet/datasets/{key}")
    def dataset_definition(key: str):
        record = service.wb.library.definition(key)
        if record["benchmark"] != "custom":
            raise ValueError("Self-test supports custom datasets only.")
        return {"name": record["name"], "rows": record['rows']}

    @app.get("/v1/intranet/drafts/{key}")
    def get_draft(key: str):
        return service.db.get_document("datasetDrafts", key)

    @app.post("/v1/intranet/operations/{kind}", status_code=202)
    def enqueue(kind: str, value: dict):
        result = service.enqueue(kind, value)
        return service.status(result["id"])

    @app.get("/v1/intranet/operations/{key}")
    def status(key: str):
        return service.status(key)

    @app.post("/v1/intranet/bundles/inspect")
    def inspect(value: dict):
        from .portable import PortableResources
        return PortableResources(service).inspect(value.get("filename", ""))
