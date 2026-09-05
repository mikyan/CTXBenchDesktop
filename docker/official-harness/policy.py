"""Apply Desktop's offline/resource policy to upstream evaluator child containers.

The test selection, patch application and scoring remain upstream implementations.
Both upstream Docker transports (SDK and CLI) need the same boundary.
"""
import os
import json
import subprocess
import uuid
from pathlib import Path


def record_image(image: str):
    target = os.environ.get("CTXBENCH_GRADE_IMAGES_PATH")
    if target:
        path = Path(target)
        previous = json.loads(path.read_text()) if path.exists() else []
        path.write_text(json.dumps(sorted(set(previous) | {image})))


def configure():
    from docker.models.containers import ContainerCollection
    original_create = ContainerCollection.create
    cpus = float(os.environ.get("CTXBENCH_GRADER_CPUS", "4"))
    memory = os.environ.get("CTXBENCH_GRADER_MEMORY", "8g")
    scope = os.environ.get("CTXBENCH_GRADE_SCOPE", "standalone")

    def create(self, *args, **kwargs):
        kwargs.pop("network", None)
        kwargs.update(network_mode="none", nano_cpus=int(cpus * 1e9), mem_limit=memory,
                      pids_limit=1024, cap_drop=["ALL"], security_opt=["no-new-privileges:true"])
        kwargs["labels"] = {**kwargs.get("labels", {}), "io.ctxbench.grade-scope": scope}
        container = original_create(self, *args, **kwargs)
        record_image(container.attrs["Image"])
        return container
    ContainerCollection.create = create

    from agentbench.environments.docker import DockerEnvironment

    def start(self):
        name = f"ctxbench-grade-{uuid.uuid4().hex[:12]}"
        command = [self.config.executable, "run", "-d", "--network=none", "--cpus", str(cpus),
                   "--memory", memory, "--pids-limit", "1024", "--cap-drop=ALL",
                   "--security-opt=no-new-privileges:true", "--label", f"io.ctxbench.grade-scope={scope}",
                   "--name", name, "-w", self.config.cwd, *self.config.run_args,
                   self.config.image, "sleep", self.config.container_timeout]
        result = subprocess.run(command, capture_output=True, text=True, timeout=3600, check=True)
        self.container_id = result.stdout.strip()
        inspected = subprocess.run([self.config.executable, "inspect", "--format", "{{.Image}}", self.container_id], capture_output=True, text=True, timeout=30, check=True)
        record_image(inspected.stdout.strip())
        if self.config.cwd == "/project/testbed":
            moved = self.execute("mkdir -p /project && mv /testbed /project", timeout=False)
            if moved["returncode"]:
                raise RuntimeError(moved["output"])
        self._capture_container_environment()
    DockerEnvironment._start_container = start
