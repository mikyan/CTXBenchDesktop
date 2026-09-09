import { useEffect, useRef, useState } from "react";
import { useI18n } from "../i18n";
import { workerRequest } from "../lib/desktop";
import { terminalOperatorJob, operatorKindLabel, type OperatorJob } from "../lib/intranet";
import { ConfirmDialog, FormError } from "./Dialogs";

export function OperatorJobPanel({ initial, onCompleted, onStatusChange, controls = false }: { initial: OperatorJob; onCompleted?: (job: OperatorJob) => void; onStatusChange?: (job: OperatorJob) => void; controls?: boolean }) {
  const { t } = useI18n();
  const ref = useRef<HTMLElement>(null);
  useEffect(() => { if (controls) ref.current?.scrollIntoView({ block: "nearest" }); }, [initial.id, controls]);
  const [job, setJob] = useState(initial);
  const [error, setError] = useState("");
  const [revision, refresh] = useState(0); const [cancel, setCancel] = useState(false); const [busy, setBusy] = useState(false);
  const checkingImages = job.kind === 'intranet:image-check';
  const complete = useRef(onCompleted); complete.current = onCompleted;
  const changed = useRef(onStatusChange); changed.current = onStatusChange;
  useEffect(() => { changed.current?.(job); }, [job]);
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
    if (revision || !terminalOperatorJob(initial.status)) void poll();
    return () => { alive = false; clearTimeout(timer); };
  }, [initial, revision]);
  const control = async (action: string) => {
    setBusy(true); setCancel(false); setError("");
    try { await workerRequest(`/operations/${job.id}/${action}`, "POST"); refresh((value) => value + 1); }
    catch (cause) { setError(String(cause)); } finally { setBusy(false); }
  };
  return <section ref={ref} className="operator-job" aria-label={t("Operation progress")}>
    <strong>{t(operatorKindLabel(job.kind))} · {t(job.status)}</strong>
    <p><code>{job.id}</code> · {t("Runs in the persistent local evaluation queue. Leaving this page does not stop it.")}</p>
    {controls && <div className="form-actions">{["queued", "running", "paused"].includes(job.status) && <button type="button" className="button secondary" disabled={busy} onClick={() => setCancel(true)}>{t(checkingImages ? "Cancel image check" : "Cancel installation")}</button>}{["failed", "cancelled", "paused"].includes(job.status) && <button type="button" className="button secondary" disabled={busy} onClick={() => void control(job.status === "paused" ? "resume" : "retry")}>{t(checkingImages ? "Retry image check" : "Retry / continue installation")}</button>}</div>}
    {job.kind === "intranet:standard-images" && <p>{t("Progress counts completed images, not downloaded bytes. Layer download and extraction details appear below; installed images have not yet passed project tests.")}</p>}
    {!terminalOperatorJob(job.status) && <progress aria-label={t("Operation progress")} max={100} value={job.kind === 'intranet:image-pull' ? undefined : job.progress?.percent ?? 0} />}
    {error && <p role="alert">{t("Progress connection lost; reconnecting. The operation may still be running.")} {error}</p>}
    {job.failure && (controls ? <FormError>{job.failure}</FormError> : <p className="form-error" role="alert">{job.failure}</p>)}
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
    {cancel && <ConfirmDialog title={t(checkingImages ? "Cancel image check?" : "Cancel installation?")} description={t(checkingImages ? "Stop checking registry metadata? Completed checks are kept. An in-flight registry request may take up to 20 seconds to finish." : "Stop this download operation? Completed images and Docker's cached layers are kept. You can retry later without downloading completed images again.")} confirmLabel={t(checkingImages ? "Cancel image check" : "Cancel installation")} onCancel={() => setCancel(false)} onConfirm={() => void control("cancel")} />}
  </section>;
}
