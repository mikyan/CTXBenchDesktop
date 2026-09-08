import { useEffect, useState } from "react";
import { useI18n } from "../i18n";
import { saveText, workerRequest } from "../lib/desktop";
import { selectedProjectImages, standardImageError, type StandardImagePlan } from "../lib/standard-images";
import { type OperatorJob, terminalOperatorJob } from "../lib/intranet";
import { ConfirmDialog, FormError, Modal } from "./Dialogs";
import { OperatorJobPanel } from "./OperatorJobPanel";

export function StandardImageInstaller({ dataset, name, onClose }: { dataset: string; name: string; onClose: () => void }) {
  const { t } = useI18n();
  const [plan, setPlan] = useState<StandardImagePlan>(); const [selected, setSelected] = useState<string[]>([]);
  const [query, setQuery] = useState(""); const [error, setError] = useState("");
  const [busy, setBusy] = useState(false); const [confirm, setConfirm] = useState(false);
  const [job, setJob] = useState<OperatorJob>(); const [revision, refresh] = useState(0);
  useEffect(() => {
    let alive = true; setBusy(true); setError("");
    void workerRequest<StandardImagePlan>(`/datasets/${dataset}/project-images`).then((next) => {
      if (!alive) return;
      setPlan(next); setSelected((ids) => ids.length ? ids : next.tasks.slice(0, 1).map((row) => row.id));
      setJob(next.operations.at(-1));
    }).catch((cause) => { if (alive) setError(standardImageError(cause)); }).finally(() => { if (alive) setBusy(false); });
    return () => { alive = false; };
  }, [dataset, revision]);
  const images = plan ? selectedProjectImages(plan, selected) : [];
  const missing = images.filter((row) => !row.installed);
  const incompatible = images.some((row) => row.installed && !row.compatible);
  const active = job && (!terminalOperatorJob(job.status) || job.status === "paused");
  const visible = plan?.tasks.filter((row) => `${row.id} ${row.repository}`.toLowerCase().includes(query.toLowerCase())) ?? [];
  const run = async (action: () => Promise<void>) => {
    setBusy(true); setError("");
    try { await action(); } catch (cause) { setError(standardImageError(cause)); } finally { setBusy(false); }
  };
  const install = () => {
    setConfirm(false);
    void run(async () => setJob(await workerRequest<OperatorJob>("/intranet/operations/standard-images", "POST", { dataset, taskIds: selected, confirmed: true })));
  };
  return <Modal title={`${t("Install project images")} · ${name}`} onClose={onClose} busy={busy}>
    <div className="standard-image-installer">
    <p>{t("The dataset file contains tasks; project images contain each project's tools and dependencies. The four application images do not include these project images.")}</p>
    {job ? <OperatorJobPanel key={job.id} initial={job} controls onStatusChange={(next) => setJob((current) => current?.status === next.status ? current : next)} onCompleted={() => refresh((value) => value + 1)} /> : <div className="wizard-notice"><strong>{t("Downloads only — no model calls")}</strong><p>{t("This step downloads images to Docker in your selected WSL distribution. It does not generate knowledge, clone baselines, run setup commands or validate tests. CTXBench still prepares and validates baseline-specific dependencies when you run an experiment.")}</p></div>}
    {error && <FormError>{t(error)}</FormError>}
    {!plan && busy && <p role="status">{t("Checking installed project images…")}</p>}
    <button type="button" className="button secondary" disabled={busy} onClick={() => refresh((value) => value + 1)}>{t("Refresh image status")}</button>
    {plan && <>
      <fieldset disabled={busy || Boolean(active)} className="standard-image-selection">
        <legend>{t("1. Select the tasks you want to run")}</legend>
        <p>{t("Only the first task is selected initially. Start small; downloading every project can use hundreds of GB.")}</p>
        <label>{t("Filter tasks")}<input value={query} onChange={(event) => setQuery(event.target.value)} /></label>
        <div className="toolbar"><button type="button" className="button secondary" onClick={() => setSelected([...new Set([...selected, ...visible.map((row) => row.id)])])}>{t("Select matching tasks")}</button><button type="button" className="button secondary" onClick={() => setSelected([])}>{t("Clear selection")}</button><span>{t("{count} tasks selected", { count: selected.length })}</span></div>
        <div className="standard-image-task-list">{visible.map((row) => <label className="check-line" key={row.id}><input type="checkbox" checked={selected.includes(row.id)} onChange={(event) => setSelected((ids) => event.target.checked ? [...ids, row.id] : ids.filter((id) => id !== row.id))} /><span><strong>{row.id}</strong><small>{row.repository}</small></span></label>)}{!visible.length && <p>{t("No matching tasks")}</p>}</div>
      </fieldset>
      <section><h3>{t("2. Review required images")}</h3>
        <p role="status">{t("{total} unique images · {cached} installed · {missing} to download", { total: images.length, cached: images.length - missing.length, missing: missing.length })}</p>
        <p>{t("Evaluation storage reports {size} GiB free. This is not a download-size estimate and may not reflect free space on the Windows drive holding WSL. Check that drive before continuing.", { size: (plan.storage.freeBytes / 1024 ** 3).toFixed(1) })}</p>
        {!plan.storage.ready && <p role="alert" className="form-error">{t("Insufficient evaluation storage. Free disk space before installing.")}</p>}
        {incompatible && <p role="alert" className="form-error">{t("An installed image has the wrong platform. Resolve the conflict before retrying; existing images will not be overwritten.")}</p>}
        <details open={images.length <= 3}><summary>{t("Image names and local status")}</summary><div className="standard-image-task-list">{images.map((row) => <div key={row.reference} className="standard-image-row"><code>{row.reference}</code><span>{t(!row.installed ? "Not installed" : row.compatible ? "Installed (not test-validated)" : "Wrong platform")}</span></div>)}</div></details>
        <div className="form-actions"><button type="button" className="button primary" disabled={busy || Boolean(active) || !selected.length || incompatible || !plan.storage.ready} onClick={() => setConfirm(true)}>{t("Install selected project images")}</button>
          <button type="button" className="button secondary" disabled={busy || !images.length} onClick={() => void run(() => saveText("ctxbench-project-images.txt", images.map((row) => row.reference).join("\n") + "\n"))}>{t("Export required image names")}</button></div>
      </section>
      <details><summary>{t("Using an internal network")}</summary><p>{t("Docker must be able to reach the image registry, independently of your Provider connection. On a connected machine, install the selected images and export them with docker save; transfer and docker load them into the selected WSL Docker engine, keeping the listed tags. Refresh here to detect them. A project-image archive alone is not a complete offline benchmark bundle; baseline repositories and additional setup dependencies are also required.")}</p></details>
    </>}
    {confirm && <ConfirmDialog title={t("Download these project images?")} description={t("Download {missing} missing images for {tasks} selected tasks? Total download size is unknown until Docker resolves the layers. No model tokens will be used. Existing local images are reused and not updated.", { missing: missing.length, tasks: selected.length })} confirmLabel={t("Confirm image installation")} onCancel={() => setConfirm(false)} onConfirm={install} />}
    </div>
  </Modal>;
}
