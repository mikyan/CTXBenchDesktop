import { useEffect, useRef, useState } from "react";
import { useI18n } from "../i18n";
import { workerRequest } from "../lib/desktop";
import { terminalOperatorJob, operatorKindLabel, type OperatorJob } from "../lib/intranet";

export function OperatorJobPanel({ initial, onCompleted }: { initial: OperatorJob; onCompleted?: (job: OperatorJob) => void }) {
  const { t } = useI18n();
  const [job, setJob] = useState(initial);
  const [error, setError] = useState("");
  const complete = useRef(onCompleted); complete.current = onCompleted;
  const delivered = useRef(new Set<string>());
  useEffect(() => {
    if (job.status === "completed" && !delivered.current.has(job.id)) { delivered.current.add(job.id); complete.current?.(job); }
  }, [job]);
  useEffect(() => {
    let alive = true; let timer: ReturnType<typeof setTimeout>;
    setJob(initial); setError("");
    const poll = async () => {
      try {
        const next = await workerRequest<OperatorJob>(`/intranet/operations/${initial.id}`);
        if (!alive) return;
        setJob(next); setError("");
        if (!terminalOperatorJob(next.status)) timer = setTimeout(() => void poll(), 2000);
      } catch (cause) { if (alive) { setError(String(cause)); timer = setTimeout(() => void poll(), 5000); } }
    };
    if (!terminalOperatorJob(initial.status)) void poll();
    return () => { alive = false; clearTimeout(timer); };
  }, [initial]);
  return <section className="operator-job" aria-label={t("Operation progress")}>
    <strong>{t(operatorKindLabel(job.kind))} · {t(job.status)}</strong>
    <p><code>{job.id}</code> · {t("Runs in the persistent Worker queue. Leaving this page does not stop it.")}</p>
    {!terminalOperatorJob(job.status) && <progress aria-label={t("Operation progress")} max={100} value={job.progress?.percent ?? 0} />}
    {error && <p role="alert">{t("Progress connection lost; reconnecting. The operation may still be running.")} {error}</p>}
    {job.failure && <p className="form-error" role="alert">{job.failure}</p>}
    {job.progress?.log && <details open={!terminalOperatorJob(job.status)}><summary>{t("Operation log")}</summary><pre>{job.progress.log}</pre></details>}
    {job.result?.imageId && <p>{t("New image (existing images unchanged)")}: <code>{job.result.tag}</code><br /><code>{job.result.imageId}</code></p>}
    {job.result?.path && <p>{t("Resource ZIP in Worker directory")}: <code>{job.result.path}</code><br />SHA-256: <code>{job.result.sha256}</code></p>}
    {job.result?.reports && <><p>{t("No Agent was called. Review baseline failures manually; an exit code alone is not proof of a behavioral regression.")}</p>
      {job.result.reports.map((report) => <details key={report.taskId}><summary>{report.taskId} · {t(report.candidateReady ? "Candidate passed self-test; review required" : "Self-test needs attention")}</summary>
        {report.failure && <p role="alert">{report.failure}</p>}
        {Object.entries(report.phases).map(([name, phase]) => <div key={name}><h4>{t(name)} · {t("Exit code")}: {phase.exitCode} {phase.infrastructureError && `· ${t("Environment error")}`}</h4><pre>{phase.log}</pre></div>)}
      </details>)}
    </>}
    {job.status === "completed" && <p>{t("Completed without model token usage.")}</p>}
  </section>;
}
