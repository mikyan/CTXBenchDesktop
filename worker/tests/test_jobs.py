import tempfile
import time
import unittest
from pathlib import Path

from worker.ctxbench_worker.database import Database
from worker.ctxbench_worker.jobs import JobWorker
from worker.ctxbench_worker.models import ModelConfig, ResourcePolicy, RunSpec
from worker.ctxbench_worker.runner import MockRunner


class JobWorkerTests(unittest.TestCase):
    def test_queued_job_runs_and_persists_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = Database(root / "state.sqlite3")
            worker = JobWorker(database, MockRunner(), poll_seconds=0.01)
            worker.start()
            job = worker.enqueue(
                RunSpec(
                    run_id="run-one",
                    mode="solve",
                    image="mock",
                    workspace=str(root / "repo"),
                    output_dir=str(root / "result"),
                    prompt="Fix it",
                    model=ModelConfig("mock", "deterministic", "off", 4096),
                    resources=ResourcePolicy(network="offline"),
                )
            )
            deadline = time.monotonic() + 2
            persisted = database.get_job(str(job["id"]))
            while persisted["status"] not in {"completed", "failed"} and time.monotonic() < deadline:
                time.sleep(0.01)
                persisted = database.get_job(str(job["id"]))
            worker.stop()
            self.assertEqual(persisted["status"], "completed")
            self.assertEqual(persisted["result"]["run_id"], "run-one")
            self.assertTrue((root / "result" / "result.json").is_file())

    def test_running_jobs_are_recovered_after_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "state.sqlite3")
            queued = database.enqueue_job("solve", {"run_id": "run"})
            claimed = database.claim_job()
            self.assertEqual(claimed["status"], "running")
            self.assertEqual(database.recover_interrupted_jobs(), 1)
            self.assertEqual(database.get_job(str(queued["id"]))["status"], "queued")


if __name__ == "__main__":
    unittest.main()
