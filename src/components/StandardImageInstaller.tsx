import { useEffect, useState } from "react";
import { useI18n } from "../i18n";
import { saveText, workerRequest } from "../lib/desktop";
import { availableImageTasks, imageStatus, normalizeProjectImageAddress, selectedProjectImages, standardImageError, type StandardImagePlan } from "../lib/standard-images";
import { type CompanyProfileRecord, type OperatorJob, terminalOperatorJob } from "../lib/intranet";
import { ConfirmDialog, FormError, Modal } from "./Dialogs";
import { OperatorJobPanel } from "./OperatorJobPanel";
import { CompanyProfilePicker } from "./CompanyProfilePicker";

export function StandardImageInstaller({ dataset, name, onClose, onExperiment }: { dataset: string; name: string; onClose: () => void; onExperiment?: (selection: { taskIds: string[]; profile?: CompanyProfileRecord }) => void }) {
  const { t } = useI18n();
  const [plan, setPlan] = useState<StandardImagePlan>(); const [selected, setSelected] = useState<string[]>([]);
  const [query, setQuery] = useState(""); const [error, setError] = useState("");
  const [busy, setBusy] = useState(false); const [confirm, setConfirm] = useState(false);
  const [job, setJob] = useState<OperatorJob>(); const [revision, refresh] = useState(0);
  const [profile, setProfile] = useState<CompanyProfileRecord>();
  const [addresses, setAddresses] = useState<Record<string, string>>({}); const [saved, setSaved] = useState(false);
  const dirty = Object.keys(addresses).length > 0;
  const profileId = profile?.id ?? "";
  useEffect(() => {
    let alive = true; setBusy(true); setError("");
    void workerRequest<StandardImagePlan>(`/datasets/${dataset}/project-images${profileId ? `?profileId=${encodeURIComponent(profileId)}` : ""}`).then((next) => {
      if (!alive) return;
      setPlan(next); setSelected((ids) => ids.length ? ids : next.tasks.slice(0, 1).map((row) => row.id));
      setJob(next.operations.at(-1));
    }).catch((cause) => { if (alive) setError(standardImageError(cause)); }).finally(() => { if (alive) setBusy(false); });
    return () => { alive = false; };
  }, [dataset, revision, profileId]);
  const images = plan ? selectedProjectImages(plan, selected) : [];
  const missing = images.filter((row) => !row.installed);
  const incompatible = images.some((row) => row.installed && !row.compatible);
  const blocked = missing.some((row) => row.pullAllowed === false);
  const active = job && (!terminalOperatorJob(job.status) || job.status === "paused");
  const visible = plan?.tasks.filter((row) => `${row.id} ${row.repository}`.toLowerCase().includes(query.toLowerCase())) ?? [];
  const run = async (action: () => Promise<void>) => {
    setBusy(true); setError("");
    try { await action(); } catch (cause) { setError(standardImageError(cause)); } finally { setBusy(false); }
  };
  const install = () => {
    setConfirm(false);
    void run(async () => setJob(await workerRequest<OperatorJob>("/intranet/operations/standard-images", "POST", { dataset, datasetRevision: plan?.datasetRevision, imageSourcesRevision: plan?.imageSources?.revision, taskIds: selected, confirmed: true, ...(profileId ? { profileId } : {}) })));
  };
  const changeAddress = (source: string, value: string) => {
    setSaved(false); setAddresses((current) => { const next = { ...current }; const stored = plan?.imageSources?.overrides.find((row) => row.source === source)?.target ?? ''; if (value === stored) delete next[source]; else next[source] = value; return next; });
  };
  const saveAddresses = () => void run(async () => {
    const overrides = Object.entries(addresses).map(([source, target]) => ({ source, target: normalizeProjectImageAddress(target) }));
    await workerRequest(`/datasets/${dataset}/project-image-sources`, 'PUT', { overrides, expectedRevision: plan?.imageSources?.revision, datasetRevision: plan?.datasetRevision, ...(profileId ? { profileId } : {}) });
    setAddresses({}); setPlan(undefined); setSaved(true); refresh((value) => value + 1);
  });
  return <Modal title={`${t("Install project images")} · ${name}`} onClose={onClose} busy={busy} warnOnClose dirty={dirty}>
    <div className="standard-image-installer">
    <p>{t("The dataset file contains tasks; project images contain each project's tools and dependencies. The four application images do not include these project images.")}</p>
    <fieldset disabled={busy || Boolean(active) || dirty}><CompanyProfilePicker value={profileId} preparationOnly onChange={(next) => { setProfile(next); setPlan(undefined); setJob(undefined); setSelected([]); setAddresses({}); setSaved(false); }} /></fieldset>
    <p>{t('Enter an internal image address below, or paste docker pull followed by the full image name. Saved exact addresses take priority over company prefix mappings. No shell command is executed.')}</p>
    {saved && <p role="status">{t('Image addresses saved. Future official tasks use them; queued jobs and existing experiments keep their frozen configuration.')}</p>}
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
        <div className="toolbar"><button type="button" className="button secondary" disabled={!visible.length || dirty} onClick={() => void run(async () => setJob(await workerRequest<OperatorJob>("/intranet/operations/image-check", "POST", { dataset, datasetRevision: plan.datasetRevision, imageSourcesRevision: plan.imageSources?.revision, taskIds: visible.map((row) => row.id), confirmed: true, ...(profileId ? { profileId } : {}) })))}>{t("Check matching tasks in registry")}</button><button type="button" className="button secondary" onClick={() => { const available = new Set(availableImageTasks(plan)); setSelected(visible.filter((row) => available.has(row.id)).map((row) => row.id)); }}>{t("Select only tasks with available images")}</button></div>
        <p>{t("Availability checks expire after 15 minutes. Missing, unchecked, login-required and unreachable images are not selected automatically. A subset experiment reports only your selected task IDs, not a full-suite score.")}</p>
        <div className="standard-image-task-list">{visible.map((row) => <label className="check-line" key={row.id}><input type="checkbox" checked={selected.includes(row.id)} onChange={(event) => setSelected((ids) => event.target.checked ? [...ids, row.id] : ids.filter((id) => id !== row.id))} /><span><strong>{row.id}</strong><small>{row.repository}</small><small>{[...new Set(row.images.map((ref) => plan.images.find((image) => image.reference === ref)).filter((image) => image !== undefined).map((image) => t(imageStatus(image))))].join(" · ")}</small></span></label>)}{!visible.length && <p>{t("No matching tasks")}</p>}</div>
      </fieldset>
      <section><h3>{t("2. Review required images")}</h3>
        {plan.imageSources ? <fieldset className="project-image-addresses" disabled={busy || Boolean(active)}><legend>{t('Download addresses for selected images')}</legend>
          <p>{t('Use the same project image mirrored into your registry, not an unrelated base image. An address change does not prove equivalent image contents; setup and test validation still run later.')}</p>
          <p>{t(profileId ? 'Addresses are remembered under the selected company profile. Select that same profile for later knowledge generation and experiments.' : 'Addresses are remembered for these official image names under No company profile, including other datasets using the same images. They do not change custom cases or model settings.')}</p>
          {images.flatMap((row) => (row.originals ?? [row.reference]).map((source) => <div className="project-image-address" key={source}>
            <label>{t('Official image name')}<code>{source}</code></label><p>{t('Current download address')}: <code>{row.reference}</code></p>
            <label>{t('Full image address or docker pull command')}<input aria-label={`${t('Full image address or docker pull command')} · ${source}`} value={addresses[source] ?? plan.imageSources?.overrides.find((item) => item.source === source)?.target ?? ''} placeholder={`docker pull registry.company.example/project/image:latest`} spellCheck={false} autoComplete="off" onChange={(e) => changeAddress(source, e.target.value)} /></label>
            <button type="button" className="text-button" onClick={() => changeAddress(source, '')}>{t('Use default address')}</button>
          </div>))}
          <p>{t('Leave blank to inherit the company mapping or official address. Saving does not download images or overwrite existing local tags.')}</p>
          <div className="form-actions"><button type="button" className="button secondary" disabled={!dirty} onClick={saveAddresses}>{t('Save addresses and refresh')}</button><button type="button" className="text-button" disabled={!dirty} onClick={() => setAddresses({})}>{t('Discard address edits')}</button></div>
        </fieldset> : <p>{t('Editing download addresses requires the matching newer evaluation service image. Update Application images first.')}</p>}
        {dirty && <p role="status" className="wizard-notice">{t('Save or discard address edits before checking, downloading, changing profiles or creating an experiment.')}</p>}
        <p role="status">{t("{total} unique images · {cached} installed · {missing} to download", { total: images.length, cached: images.length - missing.length, missing: missing.length })}</p>
        <p>{t("Evaluation storage reports {size} GiB free. This is not a download-size estimate and may not reflect free space on the Windows drive holding WSL. Check that drive before continuing.", { size: (plan.storage.freeBytes / 1024 ** 3).toFixed(1) })}</p>
        {!plan.storage.ready && <p role="alert" className="form-error">{t("Insufficient evaluation storage. Free disk space before installing.")}</p>}
        {incompatible && <p role="alert" className="form-error">{t("An installed image has the wrong platform. Resolve the conflict before retrying; existing images will not be overwritten.")}</p>}
        <details open={images.length <= 3}><summary>{t("Image names and local status")}</summary><div className="standard-image-task-list">{images.map((row) => <div key={row.reference} className="standard-image-row"><code>{row.reference}</code>{row.originals?.some((ref) => ref !== row.reference) && <small>{row.originals.join(" / ")} →</small>}<span>{t(imageStatus(row))}</span>{row.remote?.checkedAt && <small>{new Date(row.remote.checkedAt).toLocaleString()}</small>}</div>)}</div></details>
        {blocked && <p role="alert" className="form-error">{t("Some missing images have no permitted source. Add company mappings or pull/import them in WSL first; Docker Hub fallback is disabled.")}</p>}
        <div className="form-actions"><button type="button" className="button primary" disabled={busy || dirty || Boolean(active) || !selected.length || incompatible || blocked || !plan.storage.ready} onClick={() => setConfirm(true)}>{t("Install selected project images")}</button>
          {onExperiment && <button type="button" className="button secondary" disabled={busy || dirty || Boolean(active) || !selected.length || missing.length > 0 || incompatible} onClick={() => onExperiment({ taskIds: selected, profile })}>{t("Create experiment with selected tasks")}</button>}
          <button type="button" className="button secondary" disabled={busy || dirty || !images.length} onClick={() => void run(() => saveText("ctxbench-project-images.txt", images.map((row) => row.reference).join("\n") + "\n"))}>{t("Export required image names")}</button></div>
      </section>
      <details><summary>{t("Using an internal network")}</summary><p>{t("Docker must be able to reach the image registry, independently of your Provider connection. On a connected machine, install the selected images and export them with docker save; transfer and docker load them into the selected WSL Docker engine, keeping the listed tags. Refresh here to detect them. A project-image archive alone is not a complete offline benchmark bundle; baseline repositories and additional setup dependencies are also required.")}</p></details>
    </>}
    {confirm && <ConfirmDialog title={t("Download these project images?")} description={t("Download {missing} missing images for {tasks} selected tasks? Total download size is unknown until Docker resolves the layers. No model tokens will be used. Existing local images are reused and not updated.", { missing: missing.length, tasks: selected.length })} confirmLabel={t("Confirm image installation")} onCancel={() => setConfirm(false)} onConfirm={install} />}
    </div>
  </Modal>;
}
