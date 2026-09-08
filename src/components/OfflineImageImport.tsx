import { useEffect, useState } from "react";
import { useI18n } from "../i18n";
import { selectOfflineBundle } from "../lib/desktop";
import { buildTiming } from "../lib/image-build";
import { importPhaseLabels, offlineImportStore, type OfflineImport } from "../lib/offline-import";
import { ExternalLink } from "./ExternalLink";
import { version } from "../../package.json";

export function OfflineImageImport({ distribution, disabled, state, onBegin }: { distribution: string; disabled: boolean; state?: OfflineImport; onBegin: () => void }) {
  const { t } = useI18n();
  const [path, setPath] = useState(state?.packagePath ?? "");
  const [trusted, setTrusted] = useState(false);
  const [picking, setPicking] = useState(false);
  const [error, setError] = useState("");
  const choose = async () => {
    setPicking(true); setError("");
    try { const selected = await selectOfflineBundle(); if (selected) { setPath(selected); setTrusted(false); } }
    catch (failure) { setError(failure instanceof Error && failure.message === "Offline image import requires the desktop application." ? failure.message : "Could not open the file picker. Retry in the desktop application."); }
    finally { setPicking(false); }
  };
  return <div className="setup-guidance offline-import">
    <h3>{t("Offline installation")}</h3>
    <p>{t("Already installed the desktop app? You only need ONE offline images ZIP. No separate checksum files, extraction or terminal commands are needed.")}</p>
    <ol className="offline-import-steps">
      <li><strong>{t("Download one images ZIP")}</strong><p>{t("This desktop is v{version}. On a connected computer, open the same release and download the file below, then copy it here. Do not choose Source code (zip) or the Windows .exe.", { version })}</p><pre className="offline-selected-path">{`ctxbench-images-v${version}-linux-amd64.zip`}</pre><ExternalLink destination="releases">{t("Open release downloads")}</ExternalLink></li>
      <li><strong>{t("Select the file and import")}</strong><p>{t("The app verifies all checksums, then imports four images into the selected WSL. It never downloads dependencies or runs scripts from the package.")}</p>
        <button className="button secondary" disabled={disabled || picking} onClick={() => void choose()}>{t(picking ? "Choosing a package…" : "Select offline images ZIP")}</button>
        {path && <pre className="offline-selected-path">{path}</pre>}
        <label className="offline-confirm"><input type="checkbox" checked={trusted} disabled={disabled || picking} onChange={(event) => setTrusted(event.target.checked)} />{t("I trust this package's source and have paused experiments and stopped the worker.")}</label>
        <button className="button primary" disabled={disabled || picking || !path || !trusted || !distribution.trim()} onClick={() => { onBegin(); setError(""); void offlineImportStore.start(distribution, path); }}>{t("Verify and import images")}</button>
      </li>
      <li><strong>{t("Start the worker after import")}</strong><p>{t("After import, open Settings → Runtime & diagnostics and start the worker. Nothing starts automatically.")}</p></li>
    </ol>
    <details><summary>{t("Have an older split package?")}</summary><p>{t("Keep every old image part and support file in one folder. Use the same file picker and select ctxbench-images-manifest.json instead of a ZIP. Missing parts will be reported before import.")}</p><p>{t("Packages larger than GitHub's 2 GiB limit still use this legacy split format.")}</p></details>
    <p>{t("Python 3.10+ and Docker must be installed in the selected WSL. This package does not include datasets, baseline repositories or task test images.")}</p>
    {error && <p role="alert">{t(error)}</p>}
  </div>;
}

export function OfflineImportProgress({ state }: { state: OfflineImport }) {
  const { t } = useI18n();
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    if (state.status !== "running") return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [state.id, state.status]);
  const timing = buildTiming(state, now);
  const running = state.status === "running";
  const complete = state.status === "completed";
  const fraction = state.total > 0 ? state.completed / state.total : undefined;
  const percent = fraction === undefined ? undefined : Math.floor(fraction * 100);
  return <section className={`image-build-progress ${state.status}`} aria-labelledby="offline-progress-title" aria-busy={running}>
    <div className="image-build-heading"><h3 id="offline-progress-title">{t("Offline image import progress")}</h3><span>{state.distribution}</span></div>
    <p role="status">{t(complete ? "Offline images imported" : running ? importPhaseLabels[state.importPhase] : "Offline image import failed")}</p>
    <progress aria-label={t("Current import stage progress")} max={1} value={complete ? 1 : running ? fraction : fraction ?? 0} />
    <div className="image-build-metrics">{running && percent !== undefined && <strong>{t("Current stage: {percent}%", { percent })}</strong>}<span>{t("Elapsed: {time}", { time: `${Math.floor(timing.elapsed / 60_000)}:${String(Math.floor(timing.elapsed / 1000) % 60).padStart(2, "0")}` })}</span></div>
    <p>{t("Progress applies to the current stage. After all bytes reach Docker, unpacking and image verification may still take time.")}</p>
    {running && timing.silent > 30_000 && <p role="status">{t("Docker may be unpacking large image layers without output. Import is still awaiting a result; do not start another import.")}</p>}
    <details open={state.status === "failed"}><summary>{t("Technical details (redacted)")}</summary><pre className="image-build-log">{state.lines.join("\n") || t("Waiting for Docker output…")}</pre></details>
    {state.omitted > 0 && <p>{t("Showing recent output only; {count} earlier lines were discarded to limit memory use.", { count: state.omitted })}</p>}
    <p>{t("You can leave this page and return while the app stays open. Import status is kept for this app session.")}</p>
  </section>;
}
