import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { Check, CircleAlert, Copy, Download, FileCode, LoaderCircle, RefreshCw } from "lucide-react";
import { useI18n } from "../i18n";
import { controlWorker, getDeploymentInfo } from "../lib/desktop";
import { activityState, diagnosticReport, prerequisiteLabels, recoveryActions, recoveryLabels, setupCommands, setupMessage, type RecoveryAction, type DeploymentInfo, type WorkerAction, type WorkerActionResult } from "../lib/infrastructure";
import { WslDistributionPicker } from "./WslDistributionPicker";
import { ExternalLink } from "./ExternalLink";
import { imageBuildStore } from "../lib/image-build";
import { ImageBuildProgress } from "./ImageBuildProgress";
import { offlineImportStore } from "../lib/offline-import";
import { OfflineImageImport, OfflineImportProgress } from "./OfflineImageImport";
import { offlineExportStore } from "../lib/offline-export";
import { OfflineImageExport, OfflineExportProgress } from "./OfflineImageExport";
import { RuntimeSafety } from "./RuntimeSafety";

export function InfrastructureSetup({ distribution, onDistribution, onDiagnose, onBusy, diagnosing, view = "all", onSection, onExperiments, onKnowledge }: {
  distribution: string; onDistribution: (name: string) => void; onDiagnose: (distribution?: string) => void; onBusy: (busy: boolean) => void; diagnosing: boolean;
  view?: "runtime" | "images" | "all";
  onSection?: (section: "runtime" | "images" | "credentials") => void;
  onExperiments?: () => void; onKnowledge?: () => void;
}) {
  const { t } = useI18n();
  const [mode, setMode] = useState<"offline" | "online">(() => imageBuildStore.getSnapshot()?.status === "running" ? "online" : "offline");
  const [shell, setShell] = useState<"wsl" | "powershell">("powershell");
  const [imageOperation, setImageOperation] = useState<"install" | "export">("install");
  const [info, setInfo] = useState<DeploymentInfo>();
  const [checking, setChecking] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [localAction, setActive] = useState<WorkerAction>();
  const [localResult, setResult] = useState<WorkerActionResult>();
  const [logResult, setLogResult] = useState<WorkerActionResult>();
  const build = useSyncExternalStore(imageBuildStore.subscribe, imageBuildStore.getSnapshot, imageBuildStore.getSnapshot);
  const imported = useSyncExternalStore(offlineImportStore.subscribe, offlineImportStore.getSnapshot, offlineImportStore.getSnapshot);
  const exported = useSyncExternalStore(offlineExportStore.subscribe, offlineExportStore.getSnapshot, offlineExportStore.getSnapshot);
  const active = build?.status === "running" ? "build" : imported?.status === "running" ? "import" : exported?.status === "running" ? "export" : localAction;
  const recentBuildOrImport = imported && (!build || imported.startedAt >= build.startedAt) ? imported : build;
  const recent = exported && (!recentBuildOrImport || exported.startedAt >= recentBuildOrImport.startedAt) ? exported : recentBuildOrImport;
  const result = localResult ?? (recent?.distribution === distribution ? recent.result : undefined);
  const checkedBuild = useRef(0);
  const checkedImport = useRef(0);
  const [copyMessage, setCopyMessage] = useState("");
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  useEffect(() => { onBusy(Boolean(active)); }, [active, onBusy]);
  useEffect(() => { setResult(undefined); setLogResult(undefined); setCopyMessage(""); }, [distribution]);
  useEffect(() => {
    if (!imported || imported.status === "running" || checkedImport.current === imported.id || imported.distribution !== distribution) return;
    checkedImport.current = imported.id;
    setRefresh((value) => value + 1);
    onDiagnose(distribution);
  }, [imported, distribution, onDiagnose]);
  useEffect(() => {
    if (!build || build.status === "running" || checkedBuild.current === build.id || build.distribution !== distribution) return;
    checkedBuild.current = build.id;
    setRefresh((value) => value + 1);
    onDiagnose(distribution);
  }, [build, distribution, onDiagnose]);
  useEffect(() => {
    let current = true;
    setInfo(undefined);
    if (!distribution.trim()) { setChecking(false); return; }
    setChecking(true);
    // Avoid launching WSL for every keystroke of a manually entered name.
    const timer = window.setTimeout(() => {
      void getDeploymentInfo(distribution).then((value) => { if (current) setInfo(value); })
        .catch((error) => { if (current) setResult({ ok: false, code: "activity_unknown", detail: error instanceof Error ? error.message : String(error) }); })
        .finally(() => { if (current) setChecking(false); });
    }, 600);
    return () => { current = false; window.clearTimeout(timer); };
  }, [distribution, refresh]);

  const action = async (value: WorkerAction) => {
    if (active) return;
    if (value === "build") { setResult(undefined); await imageBuildStore.start(distribution); return; }
    setActive(value); if (value === "logs") setLogResult(undefined); else setResult(undefined); onBusy(true);
    try {
      const response = await controlWorker(value, distribution);
      if (!alive.current) return;
      if (value === "logs") setLogResult(response); else setResult(response);
      if (value !== "logs") {
        const updated = await getDeploymentInfo(distribution).catch(() => undefined);
        if (alive.current && updated) setInfo(updated);
        onDiagnose(distribution);
      }
    } catch (error) { if (alive.current) (value === "logs" ? setLogResult : setResult)({ ok: false, code: "action", detail: error instanceof Error ? error.message : String(error) }); }
    finally { if (alive.current) setActive(undefined); }
  };
  const copy = async (text: string) => {
    try { await navigator.clipboard.writeText(text); setCopyMessage("Copied. Review the report before sharing; never include API keys or .env files."); }
    catch { setCopyMessage("Clipboard access failed. Select and copy the visible text manually."); }
  };
  const commands = info ? setupCommands(info, shell) : {};
  const message = result && setupMessage(result.code);
  const disabled = Boolean(active) || diagnosing || checking || !distribution.trim();
  const safety = activityState(info);
  const prerequisiteFailure = info?.checks.find((check) => !check.ok);
  const recheck = () => { setRefresh((value) => value + 1); onDiagnose(distribution); };
  const recover = (target: RecoveryAction) => {
    if (target === "check") recheck();
    else if (target === "logs") void action("logs");
    else if (target === "offline") { setMode("offline"); setImageOperation("install"); onSection?.("images"); }
    else if (target !== "downloads") { if (target === "images") setImageOperation("install"); onSection?.(target); }
  };
  return <section className="panel setup-panel" aria-labelledby="setup-heading">
    <div className="panel-header"><div><h2 id="setup-heading" tabIndex={-1}>{t(view === "images" ? "Application images" : "Install and start the worker")}</h2></div><Download size={22} aria-hidden="true" /></div>
    <div className="setup-content">
      <details className="setup-introduction"><summary>{t("Open setup guide")}</summary><p className="setup-intro">{t("WSL and Docker are the foundation, not the CTXBench worker. Complete the three steps below; no Provider key is needed for setup.")}</p>
      <ol className="setup-steps">
        <li><span>1</span><div><strong>{t("Choose the WSL distribution")}</strong><p>{t("Install Docker Engine and its Compose plugin in this same distribution.")}</p></div></li>
        <li><span>2</span><div><strong>{t("Prepare application images")}</strong><p>{t("Import offline images or build online. The Windows installer contains deployment files, not Docker images.")}</p></div></li>
        <li><span>3</span><div><strong>{t("Start and verify")}</strong><p>{t("Start the worker, wait for its health check, then configure credentials and datasets.")}</p></div></li>
      </ol>
      </details>
      <WslDistributionPicker value={distribution} onChange={onDistribution} disabled={Boolean(active) || diagnosing} />
      <RuntimeSafety info={info} distribution={distribution} checking={checking} disabled={disabled} onCheck={recheck} onStop={() => void action("stop")} onExperiments={onExperiments} onKnowledge={onKnowledge} />
      {prerequisiteFailure && <div className="setup-feedback error" role="status"><h3>{t(setupMessage(prerequisiteFailure.id).title)}</h3><p>{t(setupMessage(prerequisiteFailure.id).help)}</p><div className="toolbar">{recoveryActions(prerequisiteFailure.id).filter((target) => onSection || !["runtime", "images", "credentials", "offline"].includes(target)).map((target) => target === "downloads" ? <ExternalLink key={target} destination="releases">{t(recoveryLabels[target])}</ExternalLink> : <button key={target} className="button secondary" disabled={disabled} onClick={() => recover(target)}>{t(recoveryLabels[target])}</button>)}</div></div>}
      <div hidden={view === "runtime"} className="settings-stack">
      <p>{t("Images belong to the selected WSL distribution. Choose one operation below.")}</p>
      <div className="segmented-actions" role="group" aria-label={t("Application images")}><button className="button secondary" aria-pressed={imageOperation === "install"} onClick={() => setImageOperation("install")}>{t("Install or build")}</button><button className="button secondary" aria-pressed={imageOperation === "export"} onClick={() => setImageOperation("export")}>{t("Export customized images")}</button></div>
      <div hidden={imageOperation !== "install"} className="settings-stack">
      <fieldset className="setup-mode"><legend>{t("How will you prepare images?")}</legend>
        <label><input type="radio" name="setup-mode" checked={mode === "offline"} disabled={Boolean(active)} onChange={() => setMode("offline")} />{t("Internal network / offline images")}</label>
        <label><input type="radio" name="setup-mode" checked={mode === "online"} disabled={Boolean(active)} onChange={() => setMode("online")} />{t("Internet available / build images")}</label>
      </fieldset>
      {mode === "offline" ? <OfflineImageImport key={distribution} distribution={distribution} disabled={disabled} ready={safety.canReplace} state={imported?.distribution === distribution ? imported : undefined} onBegin={() => setResult(undefined)} /> : <div className="setup-guidance">
        <h3>{t("Online installation")}</h3><p>{t("Build images downloads base images and dependencies and may take several minutes. Check registry access and free disk space first. The build does not start experiments or call a Provider.")}</p>
        {!safety.canReplace && <p>{t("Complete the image update safety check above before importing or building. File selection is still available.")}</p>}
        <button className="button secondary" disabled={disabled || !safety.canReplace} onClick={() => void action("build")}>{t("Build images")}</button>
      </div>}
      </div><div hidden={imageOperation !== "export"}>
      <OfflineImageExport key={distribution} distribution={distribution} disabled={disabled} state={exported} onBegin={() => setResult(undefined)} />
      </div></div>
      {result && message && <div className={`setup-feedback ${result.ok ? "success" : "error"}`} role={result.ok ? "status" : "alert"}>
        <h3>{t(message.title)}</h3><p>{t(message.help)}</p>
        <div className="toolbar">{recoveryActions(result.code).filter((target) => onSection || !["runtime", "images", "credentials", "offline"].includes(target)).map((target) => target === "downloads" ? <ExternalLink key={target} destination="releases">{t(recoveryLabels[target])}</ExternalLink> : <button key={target} className="button secondary" disabled={disabled} onClick={() => recover(target)}>{t(recoveryLabels[target])}</button>)}</div>
        {result.detail && <details><summary>{t("Technical details (redacted)")}</summary><pre>{t(result.detail)}</pre></details>}
        <button className="button secondary" onClick={() => void copy(diagnosticReport(info, result))}><Copy size={16} />{t("Copy diagnostic report")}</button>
      </div>}
      {build && recent === build && build.distribution === distribution && <ImageBuildProgress key={build.id} build={build} />}
      {imported && recent === imported && imported.distribution === distribution && <OfflineImportProgress key={imported.id} state={imported} />}
      {exported && recent === exported && exported.distribution === distribution && <OfflineExportProgress key={exported.id} state={exported} />}
      {logResult && <div className={`setup-feedback ${logResult.ok ? "neutral" : "error"}`} role={logResult.ok ? "status" : "alert"}><h3>{t(setupMessage(logResult.code).title)}</h3><p>{t(setupMessage(logResult.code).help)}</p><pre className="image-build-log">{t(logResult.detail) || t("No container logs were returned.")}</pre></div>}

      <div hidden={view === "images"} className="settings-stack">
      <div className="toolbar"><button className="button primary" disabled={disabled || !safety.known || safety.tasks.length > 0} onClick={() => void action("start")}>{t("Start worker")}</button><button className="button secondary" disabled={disabled} onClick={() => void action("logs")}>{t("Read container logs")}</button></div>
      <p>{t("Start worker uses local images only: no build, no pull. Stop worker does not delete stored data. Pause active experiments before stopping or replacing the worker.")}</p>
      <details><summary>{t("Where are my datasets and results stored?")}</summary><p>{t("Files selected in the app are transferred automatically. The managed service directory is not a download folder; you do not need sudo or direct write permission to import a dataset.")}</p><p>{t("WSL storage location")}: <code>{info?.dataDirectory ?? t("Not available")}</code></p><p>{t("Advanced deployments may set CTXBENCH_HOST_DATA_DIR to another WSL directory. Changing it does not migrate existing data. Keep the old directory and complete a verified migration before switching.")}</p></details>
      <details className="prerequisite-details"><summary>{t("Deployment prerequisites")}{info && ` · ${info.checks.filter((check) => check.ok).length}/${info.checks.length}`}</summary>
      <div className="setup-check-header"><h3>{t("Deployment prerequisites")}</h3><button className="button secondary" disabled={disabled || checking} onClick={() => setRefresh((value) => value + 1)}><RefreshCw size={16} className={checking ? "spin" : ""} />{t("Check prerequisites")}</button></div>
      <p>{t("This check is read-only: it checks the deployment file, Compose, images and data directory without installing or starting containers.")}</p>
      {checking && <p role="status"><LoaderCircle size={18} className="spin" /> {t("Checking deployment prerequisites…")}</p>}
      {!distribution.trim() && <p className="setup-callout">{t("Select an installed WSL distribution first.")}</p>}
      {info && <>
        <dl className="setup-paths"><div><dt>{t("Windows deployment file")}</dt><dd>{info.composePath}</dd></div><div><dt>{t("Path inside selected WSL")}</dt><dd>{info.wslComposePath || t("Not available")}</dd></div></dl>
        <ul className="setup-checks">{info.checks.map((check) => <li key={check.id}>
          {check.ok ? <Check className="icon-success" size={20} /> : <CircleAlert className="icon-warning" size={20} />}
          <div><strong>{t(prerequisiteLabels[check.id] ?? check.id)} · {t(check.ok ? "Ready" : "Action needed")}</strong>
            {!check.ok && <p>{t(setupMessage(check.id).help)}</p>}
            {check.detail && <pre>{check.detail}</pre>}
          </div>
        </li>)}</ul>
        {info.containers.length > 0 && <details><summary>{t("Current container status")}</summary><pre>{info.containers.join("\n")}</pre></details>}
      </>}
      </details>
      {info?.checks.some((check) => !check.ok) && <p className="setup-callout">{t("Action needed")} · {info.checks.filter((check) => !check.ok).map((check) => t(prerequisiteLabels[check.id] ?? check.id)).join(" · ")}</p>}
      </div>
      {active && active !== "build" && active !== "import" && active !== "export" && <div className="setup-callout" role="status"><LoaderCircle className="spin" size={18} /><span>{t(active === "start" ? "Starting containers and waiting for the worker health check…" : "Reading or updating containers…")}</span></div>}
      <details className="setup-manual"><summary><FileCode size={18} /> {t("Manual commands and troubleshooting")}</summary>
        <p>{t("Commands below use the detected absolute path, so your current directory does not matter. Do not replace compose.yaml with compose.yml.")}</p>
        <label>{t("Where will you run the command?")}<select value={shell} onChange={(event) => setShell(event.target.value as "wsl" | "powershell")}><option value="powershell">Windows PowerShell</option><option value="wsl">{t("Selected WSL terminal")}</option></select></label>
        {commands.start ? <>
          <CommandBlock label={t("Start worker")} command={commands.start} onCopy={copy} />
          <CommandBlock label={t("Current container status")} command={commands.status} onCopy={copy} />
          <CommandBlock label={t("Active CTXBench containers across deployments")} command={commands.activity} onCopy={copy} />
          <CommandBlock label={t("Stop worker after pausing and waiting for tasks")} command={commands.stop} onCopy={copy} />
          {result?.code === "disk_space" && <CommandBlock label={t("Check WSL disk space (read-only)")} command={commands.space} onCopy={copy} />}
          {result?.code === "port_in_use" && <CommandBlock label={t("Find containers publishing port 48173 (read-only)")} command={commands.port} onCopy={copy} />}
          {info?.checks.some((check) => check.id === "data_directory" && !check.ok) && commands.directory && <CommandBlock label={t("Create the missing WSL data directory (requires sudo)")} command={commands.directory} onCopy={copy} />}
          {mode === "online" && <CommandBlock label={t("Build images")} command={commands.build} onCopy={copy} />}
        </> : <p>{t("Choose a distribution and pass the deployment-file check to generate exact commands. No relative-path fallback will be shown.")}</p>}
        <p><ExternalLink destination="wsl">{t("WSL installation guide")}</ExternalLink> · <ExternalLink destination="docker">{t("Docker Engine and Compose installation guide")}</ExternalLink></p>
        <p>{t("For internal machines, follow your organization's approved installation, registry and certificate policies. Never put credentials in commands you share.")}</p>
      </details>
      {copyMessage && <p role="status">{t(copyMessage)}</p>}
    </div>
  </section>;
}

export function CommandBlock({ label, command, onCopy }: { label: string; command: string; onCopy: (command: string) => Promise<void> }) {
  const { t } = useI18n();
  return <div className="setup-command"><div><strong>{label}</strong><button type="button" className="button secondary" aria-label={t("Copy command: {label}", { label })} onClick={() => void onCopy(command)}><Copy size={16} />{t("Copy command")}</button></div><pre><code>{command}</code></pre></div>;
}
