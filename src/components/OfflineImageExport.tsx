import { useEffect, useState } from "react";
import { useI18n } from "../i18n";
import { listLocalImages, selectImageExportPath } from "../lib/desktop";
import { buildTiming } from "../lib/image-build";
import { defaultExportImages, exportPhaseLabels, offlineExportStore, validExportImages, type OfflineExport } from "../lib/offline-export";
import { setupMessage, type WorkerActionResult } from "../lib/infrastructure";
import { version } from "../../package.json";

export function OfflineImageExport({ distribution, disabled, state, onBegin }: { distribution: string; disabled: boolean; state?: OfflineExport; onBegin: () => void }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const [images, setImages] = useState(() => (state?.distribution === distribution ? state.images : defaultExportImages).map(({ role, reference }) => ({ role, reference })));
  const [available, setAvailable] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [listError, setListError] = useState<WorkerActionResult>();
  const [path, setPath] = useState(state?.distribution === distribution ? state.packagePath : "");
  const [trusted, setTrusted] = useState(false);
  const [picking, setPicking] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!open || !distribution.trim()) return;
    let alive = true;
    setLoading(true); setListError(undefined);
    void listLocalImages(distribution).then((result) => {
      if (alive) { setAvailable(result.images); setListError(result.error ?? undefined); }
    }).catch(() => { if (alive) { setAvailable([]); setListError({ ok: false, code: "docker", detail: "Could not list local Docker images. Manual entry is still available." }); } })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [open, distribution, refresh]);
  const choose = async () => {
    setPicking(true); setError("");
    try { const selected = await selectImageExportPath(); if (selected) setPath(selected); }
    catch { setError("Could not open the file picker. Retry in the desktop application."); }
    finally { setPicking(false); }
  };
  return <details className="setup-guidance offline-export" onToggle={(event) => setOpen(event.currentTarget.open)}>
    <summary>{t("Package customized Docker images")}</summary>
    <p>{t("Installed extra software in an internal image? Export the four local application images as one reusable ZIP. No rebuild, download, container commit or service restart is performed.")}</p>
    {open && <>
      <p>{t("Select an existing local image for each role. Default runtime tags are prefilled; type a custom tag or choose one from the suggestions.")}</p>
      <button className="button secondary" disabled={disabled || loading} onClick={() => setRefresh((value) => value + 1)}>{t(loading ? "Listing local images…" : "Refresh local images")}</button>
      <div className="offline-export-images">{defaultExportImages.map(({ role, label }) => <label key={role}>{t(label)}<input list="export-local-image-options" autoComplete="off" spellCheck={false} value={images.find((image) => image.role === role)?.reference ?? ""} disabled={disabled}
        onChange={(event) => { setImages((current) => current.map((image) => image.role === role ? { ...image, reference: event.target.value } : image)); setTrusted(false); }} /></label>)}</div>
      <datalist id="export-local-image-options">{available.map((reference) => <option key={reference} value={reference} />)}</datalist>
      {listError && <p role="alert">{t(setupMessage(listError.code).help)} {t("Could not list local Docker images. Manual entry is still available.")}</p>}
      {!loading && !listError && available.length === 0 && <p>{t("No tagged local images found. Build or import the required images first, or enter a local image digest.")}</p>}
      {!validExportImages(images) && <p role="alert">{t(setupMessage("export_selection").help)}</p>}
      <p className="setup-callout">{t("Changes made inside a container are not image changes until saved as an image. Prefer a Dockerfile; export does not include a container's writable layer or mounted volumes. Keep each role's startup contract compatible.")}</p>
      <p>{t("Target desktop version: v{version}. This is a customized local package, not an official release. Same-version desktops can import it using Select offline images ZIP.", { version })}</p>
      <button className="button secondary" disabled={disabled || picking} onClick={() => void choose()}>{t("Choose ZIP destination")}</button>
      {path && <pre className="offline-selected-path">{path}</pre>}
      <p>{t("Choose a new filename; existing files are not overwritten. The destination needs space for compressed staging files and the final ZIP, roughly twice the compressed package size. Local ZIPs may exceed 2 GiB.")}</p>
      <label className="offline-confirm"><input type="checkbox" checked={trusted} disabled={disabled || picking} onChange={(event) => setTrusted(event.target.checked)} />{t("I saved my changes as images and checked that their layers contain no API keys, login files or private data that must not be shared.")}</label>
      <p>{t("Explicit credential environment settings are blocked. Image files and history cannot be fully audited automatically; deleting a secret in a later layer does not remove it from earlier layers.")}</p>
      <button className="button primary" disabled={disabled || picking || !path || !trusted || !validExportImages(images)} onClick={() => { onBegin(); setError(""); void offlineExportStore.start(distribution, path, images); }}>{t("Export image ZIP")}</button>
      {error && <p role="alert">{t(error)}</p>}
    </>}
  </details>;
}

export function OfflineExportProgress({ state }: { state: OfflineExport }) {
  const { t } = useI18n();
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    if (state.status !== "running") return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [state.id, state.status]);
  const running = state.status === "running";
  const timing = buildTiming(state, now);
  const fraction = state.total > 0 ? state.completed / state.total : undefined;
  return <section className={`image-build-progress ${state.status}`} aria-labelledby="offline-export-title" aria-busy={running}>
    <div className="image-build-heading"><h3 id="offline-export-title">{t("Image export progress")}</h3><span>{state.distribution}</span></div>
    <p role="status">{t(state.status === "completed" ? "Custom image ZIP exported" : running ? exportPhaseLabels[state.exportPhase] : "Image export failed")}</p>
    <progress aria-label={t("Current export stage progress")} max={1} value={state.status === "completed" ? 1 : running ? fraction : fraction ?? 0} />
    <div className="image-build-metrics"><span>{t("Elapsed: {time}", { time: `${Math.floor(timing.elapsed / 60000)}:${String(Math.floor(timing.elapsed / 1000) % 60).padStart(2, "0")}` })}</span>
      {running && fraction !== undefined && <strong>{t("Current stage: {percent}%", { percent: Math.floor(fraction * 100) })}</strong>}
      {running && state.exportPhase === "save" && <span>{t("Archive data processed: {size} MiB (total unknown)", { size: (state.completed / 1048576).toFixed(1) })}</span>}</div>
    <pre className="offline-selected-path">{state.packagePath}</pre>
    <p>{t("Export progress is per stage. Docker save has no reliable total; a percentage appears only when the current stage's total is known. Keep the app open until export and verification finish.")}</p>
    {running && timing.silent > 30000 && <p role="status">{t("Docker or compression may be quiet. Export is still awaiting a result; do not start another export.")}</p>}
    <details open={state.status === "failed"}><summary>{t("Technical details (redacted)")}</summary><pre className="image-build-log">{state.lines.join("\n") || t("Waiting for Docker output…")}</pre></details>
    {state.omitted > 0 && <p>{t("Showing recent output only; {count} earlier lines were discarded to limit memory use.", { count: state.omitted })}</p>}
    <p>{t("You can leave this page and return while the app stays open. Export status is kept for this app session.")}</p>
  </section>;
}
