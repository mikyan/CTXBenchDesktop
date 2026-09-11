import { useEffect, useState } from "react";
import type { DatasetRecord, KnowledgeArtifact } from "../domain/types";
import { useI18n } from "../i18n";
import { saveText, workerRequest } from "../lib/desktop";
import { loadLibrary, librarySources } from "../lib/case-library";
import { buildFiles, companyProfileSchema, defaultCompanyProfile, namesFromLines, operatorKindLabel, type CompanyProfileRecord, type IntranetInventory, type OperatorJob } from "../lib/intranet";
import { AgentArgsField } from "./AgentArgsField";
import { OperatorJobPanel } from "./OperatorJobPanel";
import { DatasetSelfTest } from "./DatasetSelfTest";
import { companyFeatureError } from "../lib/intranet";
import { RemoteImagePull } from './RemoteImagePull';
import { ImageRecipeGuide } from './ImageRecipeGuide';
import { BuildFilePicker } from './BuildFilePicker';

type Inspection = { filename: string; sha256: string; dataset: string; datasetId: string; images: number; baselines: number; contexts: number; conflicts: string[]; requiredBytes: number; freeBytes: number; ready: boolean };
const emptyInventory: IntranetInventory = { profiles: [], drafts: [], adaptations: [], operations: [], transferDirectory: "" };

export function IntranetWorkbench({ distribution = "", section }: { distribution?: string; section?: "Company profiles" | "Image adaptation" | "Dataset self-test" | "Portable resources" }) {
  const { t } = useI18n();
  const [localTab, setTab] = useState("Company profiles");
  const tab = section ?? localTab;
  const [inventory, setInventory] = useState(emptyInventory); const [datasets, setDatasets] = useState<DatasetRecord[]>([]);
  const [error, setError] = useState(""); const [message, setMessage] = useState(""); const [busy, setBusy] = useState(false);
  const [profile, setProfile] = useState(defaultCompanyProfile); const [selectedProfile, setSelectedProfile] = useState("");
  const [domains, setDomains] = useState(""); const [envNames, setEnvNames] = useState("");
  const [base, setBase] = useState("ctxbench/agent-pi:0.1.0"); const [recipeName, setRecipeName] = useState("");
  const [dockerfile, setDockerfile] = useState("RUN mkdir -p /opt/company\n# COPY requirements.txt /opt/company/requirements.txt\n# RUN pip install --no-cache-dir -r /opt/company/requirements.txt");
  const [files, setFiles] = useState<{ path: string; base64: string }[]>([]); const [buildNetwork, setBuildNetwork] = useState("none");
  const [trustBuild, setTrustBuild] = useState(false); const [job, setJob] = useState<OperatorJob>();
  const [recipeOpen, setRecipeOpen] = useState(false);
  const [datasetId, setDatasetId] = useState(""); const [probe, setProbe] = useState("");
  const [extraImages, setExtraImages] = useState("ctxbench/agent-pi:0.1.0");
  const [contextIds, setContextIds] = useState<string[]>([]); const [contexts, setContexts] = useState<KnowledgeArtifact[]>([]);
  const [profileIds, setProfileIds] = useState<string[]>([]); const [trustExport, setTrustExport] = useState(false);
  const [filename, setFilename] = useState(""); const [inspection, setInspection] = useState<Inspection>(); const [trustImport, setTrustImport] = useState(false);
  const refresh = async () => {
    const [value, rows] = await Promise.all([workerRequest<IntranetInventory>("/intranet"), loadLibrary().then(librarySources)]);
    setInventory(value); setDatasets(rows);
  };
  useEffect(() => { let alive = true; void Promise.all([workerRequest<IntranetInventory>("/intranet"), loadLibrary().then(librarySources)]).then(([value, rows]) => { if (alive) { setInventory(value); setDatasets(rows); } }).catch((cause) => { if (alive) setError(companyFeatureError(cause)); }); return () => { alive = false; }; }, []);
  const run = async (action: () => Promise<void>) => {
    if (busy) return; setBusy(true); setError(""); setMessage("");
    try { await action(); } catch (cause) { setError(companyFeatureError(cause)); } finally { setBusy(false); }
  };
  const loadProfile = (row: CompanyProfileRecord) => { setProfile(row.document); setDomains(row.document.providerDomains.join("\n")); setEnvNames(row.document.envNames.join("\n")); setSelectedProfile(row.id); };
  const currentProfile = () => ({ ...profile, envNames: namesFromLines(envNames), providerDomains: namesFromLines(domains) });
  const queue = async (kind: string, value: unknown) => { const queued = await workerRequest<OperatorJob>(`/intranet/operations/${kind}`, "POST", value); setJob(queued); await refresh(); };
  const chooseDataset = (id: string) => { setDatasetId(id); setProbe(""); setContextIds([]); };
  const toggle = (current: string[], key: string) => current.includes(key) ? current.filter((id) => id !== key) : [...current, key];
  const datasetPicker = (forExport = false) => <label>{t(forExport ? 'Custom case or dataset to export' : "Custom dataset")}<select value={datasetId} onChange={(e) => chooseDataset(e.target.value)}><option value="">{t(forExport ? 'Choose an existing case or dataset' : "Choose a dataset")}</option>{datasets.filter((d) => d.benchmark === "custom").map((d) => <option key={d.id} value={d.id}>{forExport ? `${t(d.id.startsWith('case-') ? 'Evaluation cases' : 'Datasets')}: ` : ''}{d.name} · {d.count}</option>)}</select></label>;
  return <section className="panel intranet-workbench" aria-labelledby="intranet-title">
    <div className="panel-header"><div>{!section && <span className="panel-kicker">{t("INTRANET ADAPTATION")}</span>}<h2 id="intranet-title">{t(section ?? "Company deployment workbench")}</h2></div><button className="button secondary" disabled={busy} onClick={() => void run(refresh)}>{t("Refresh")}</button></div>
    {!section && <p>{t("Version company settings, adapt local images, verify custom tests, and transfer pinned resources. These tools never start an Agent or modify an existing experiment.")}</p>}
    {!section && <nav className="wizard-actions" aria-label={t("Company deployment workbench")}>{["Company profiles", "Image adaptation", "Dataset self-test", "Portable resources"].map((name) => <button aria-current={tab === name ? "page" : undefined} className={`button ${tab === name ? "primary" : "secondary"}`} key={name} disabled={busy} onClick={() => { setTab(name); setError(""); setMessage(""); }}>{t(name)}</button>)}</nav>}
    <fieldset disabled={busy} className="intranet-fields">
      {tab === "Company profiles" && <>
        <p>{t("Profiles contain names and non-secret configuration only. Set API keys and endpoint environment values separately in Runtime environment. Saving creates an immutable version; apply it explicitly when creating an experiment.")}</p>
        <label>{t("Saved company profiles")}<select value={selectedProfile} onChange={(e) => { const row = inventory.profiles.find((p) => p.id === e.target.value); if (row) loadProfile(row); else { setSelectedProfile(""); setProfile(defaultCompanyProfile()); setDomains(""); setEnvNames(""); } }}><option value="">{t("New profile")}</option>{inventory.profiles.map((p) => <option key={p.id} value={p.id}>{p.document.name} · {p.id.slice(0, 8)}</option>)}</select></label>
        <div className="intranet-grid">{([['name', 'Profile name'], ['provider', 'Provider'], ['model', 'Model'], ['agentImage', 'Agent image'], ['harnessImage', 'Official harness image']] as const).map(([key, label]) => <label key={key}>{t(label)}<input value={profile[key]} onChange={(e) => setProfile({ ...profile, [key]: e.target.value })} /></label>)}</div>
        <label>{t("Environment names only")}<textarea value={envNames} onChange={(e) => setEnvNames(e.target.value)} placeholder={"OPENAI_API_KEY\nOPENAI_BASE_URL"} /></label>
        <AgentArgsField value={profile.agentArgs} onChange={(agentArgs) => setProfile({ ...profile, agentArgs })} />
        <label className="check-line"><input type="checkbox" checked={profile.offline} onChange={(e) => setProfile({ ...profile, offline: e.target.checked })} />{t("Offline preparation: use cached baselines and local images only; fail instead of fetching.")}</label>
        <details open><summary>{t("Company Docker registry")}</summary>
          <p>{t("Use prefix mappings when your company stores only some project images under different names. With any mapping configured, unmapped images must already exist locally; there is no fallback to Docker Hub. Turn off offline preparation if company downloads are allowed.")}</p>
          <p>{t("Example: swebench/sweb.eval.x86_64. → registry.company.example/swe-bench-verifield/ preserves sympy_1776_sympy-18189:latest. Replace the example hostname and keep your actual directory spelling. CTXBench needs its own mapping; SWE images do not cover it.")}</p>
          {(profile.imageMappings ?? []).map((mapping, index) => <div className="intranet-grid" key={index}>{([['source', 'Original image prefix'], ['target', 'Company image prefix']] as const).map(([key, label]) => <label key={key}>{t(label)}<input value={mapping[key]} onChange={(e) => setProfile({ ...profile, imageMappings: profile.imageMappings?.map((row, n) => n === index ? { ...row, [key]: e.target.value } : row) })} /></label>)}<button className="button secondary" onClick={() => setProfile({ ...profile, imageMappings: profile.imageMappings?.filter((_, n) => n !== index) })}>{t("Remove image mapping")}</button></div>)}
          <button className="button secondary" onClick={() => setProfile({ ...profile, imageMappings: [...profile.imageMappings ?? [], { source: "swebench/sweb.eval.x86_64.", target: "" }] })}>{t("Add image mapping")}</button>
          <p>{t("Mappings affect project image installation, knowledge preparation and evaluation when this profile is selected. They do not configure Dockerfile FROM lines, npm, pip or Maven sources. For registry login errors, pull the displayed images in the selected WSL distribution and refresh; host login credentials are not automatically shared with the evaluation service.")}</p>
        </details>
        <details><summary>{t("Exact Git mirrors")}{profile.gitMirrors.length > 0 && ` · ${profile.gitMirrors.length}`}</summary><p>{t("Map the original repository URL to a company mirror. The benchmark keeps the original repository identity and exact commit; it does not rewrite task prompts or context identities.")}</p>
        {profile.gitMirrors.map((mirror, index) => <div className="intranet-grid" key={index}>{([['repository', 'Original repository'], ['mirror', 'Company Git mirror']] as const).map(([key, label]) => <label key={key}>{t(label)}<input value={mirror[key]} onChange={(e) => setProfile({ ...profile, gitMirrors: profile.gitMirrors.map((m, n) => n === index ? { ...m, [key]: e.target.value } : m) })} /></label>)}<button className="button secondary" onClick={() => setProfile({ ...profile, gitMirrors: profile.gitMirrors.filter((_, n) => n !== index) })}>{t("Remove mirror")}</button></div>)}
        <button className="button secondary" onClick={() => setProfile({ ...profile, gitMirrors: [...profile.gitMirrors, { repository: "", mirror: "" }] })}>{t("Add Git mirror")}</button>
        </details><details><summary>{t("Provider HTTPS domains (one per line)")}</summary>
        <label>{t("Provider HTTPS domains (one per line)")}<textarea value={domains} onChange={(e) => setDomains(e.target.value)} placeholder="api.company.example" /></label>
        <p>{t("Provider domains generate a Squid configuration for your proxy image. They are not hot-applied to the running proxy. Public CA certificates can be added through image adaptation; never upload private keys.")}</p>
        </details>
        <div className="wizard-actions"><button className="button primary" onClick={() => void run(async () => { const row = await workerRequest<CompanyProfileRecord>("/intranet/profiles", "POST", currentProfile()); loadProfile(row); await refresh(); setMessage(t("Company profile version saved.")); })}>{t("Save profile version")}</button>
          <button className="button secondary" onClick={() => void run(async () => { const row = await workerRequest<CompanyProfileRecord>("/intranet/profiles", "POST", currentProfile()); await saveText("ctxbench-company-profile.json", JSON.stringify(row.document, null, 2)); await refresh(); })}>{t("Export profile JSON")}</button>
          <button className="button secondary" disabled={!selectedProfile} onClick={() => void run(async () => { const file = await workerRequest<{ filename: string; content: string }>(`/intranet/profiles/${selectedProfile}/proxy`); await saveText(file.filename, file.content); })}>{t("Export saved proxy rules")}</button>
        </div>
        <label>{t("Import profile JSON")}<input type="file" accept=".json" onChange={(e) => { const file = e.target.files?.[0]; e.target.value = ""; if (file) void run(async () => { if (file.size > 1_000_000) throw Error("Profile exceeds 1 MB."); const document = companyProfileSchema.parse(JSON.parse(await file.text())); const row = await workerRequest<CompanyProfileRecord>("/intranet/profiles", "POST", document); loadProfile(row); await refresh(); }); }} /></label>
      </>}
      {tab === "Image adaptation" && <>
        <RemoteImagePull onInstalled={setBase} />
        <ImageRecipeGuide distribution={distribution} onApply={(recipe) => { setRecipeName(recipe.name); setBase(recipe.baseImage); setDockerfile(recipe.dockerfile); setFiles(recipe.files); setBuildNetwork(recipe.network); setTrustBuild(false); setRecipeOpen(true); setMessage(t('Recipe copied. Review and confirm the build below.')); }} />
        <details open={recipeOpen} onToggle={(e) => setRecipeOpen(e.currentTarget.open)}><summary>{t('Build form / advanced Dockerfile')}</summary>
        <p>{t("Extend an existing local image without editing the benchmark baseline. FROM is pinned to its image ID automatically. The result gets a new unique tag; production tags are not replaced.")}</p>
        <div className="intranet-grid"><label>{t("Adaptation name")}<input value={recipeName} onChange={(e) => setRecipeName(e.target.value)} /></label><label>{t("Local base image")}<input value={base} onChange={(e) => setBase(e.target.value)} /></label></div>
        <label>{t("Dockerfile instructions after FROM")}<textarea rows={10} value={dockerfile} onChange={(e) => setDockerfile(e.target.value)} spellCheck={false} /></label>
        <BuildFilePicker label="Local build files (public CA, requirements, installers)" count={files.length} busy={busy} onSelect={(selected) => { void run(async () => { setFiles(await buildFiles(selected)); setTrustBuild(false); }); }} />
        <p>{t("Uploads replace the current file list. Maximum 30 MiB / 200 files; large dependencies should be baked into the local base image. Credentials and private keys must not be copied into layers.")}</p>
        {files.map((file, index) => <label key={index}>{t("Build context path")}<input value={file.path} onChange={(e) => setFiles(files.map((f, n) => n === index ? { ...f, path: e.target.value } : f))} /></label>)}
        <label>{t("Build network")}<select value={buildNetwork} onChange={(e) => setBuildNetwork(e.target.value)}><option value="none">{t("Offline (no build network)")}</option><option value="bridge">{t("Network enabled (use company sources in recipe)")}</option></select></label>
        <label className="check-line"><input type="checkbox" checked={trustBuild} onChange={(e) => setTrustBuild(e.target.checked)} />{t("I trust this recipe and base image. Build commands execute locally; I have checked that files and layers contain no credentials.")}</label>
        <button className="button primary" disabled={!trustBuild || !recipeName.trim() || !base.trim()} onClick={() => void run(() => queue("image-build", { name: recipeName, baseImage: base, dockerfile, files, network: buildNetwork }))}>{t("Build adapted image")}</button>
        <p>{t("Image metadata and compatibility labels are recorded, but are not a protocol test. Validate a custom Agent with a small benchmark before using it in a campaign.")}</p>
        </details>
        {inventory.adaptations.length > 0 && <details><summary>{t("Saved image recipes")}</summary>{inventory.adaptations.map((a) => <div key={a.id}><p>{a.name}: <code>{a.tag}</code></p><button className="button secondary" onClick={() => void run(async () => { const record = await workerRequest<{ recipe: unknown }>(`/intranet/images/${a.id}`); await saveText("ctxbench-image-recipe.json", JSON.stringify(record, null, 2)); })}>{t("Export recipe and image receipt")}</button></div>)}</details>}
      </>}
      {tab === "Dataset self-test" && <>
        <p>{t("Create or restore drafts in Datasets → Create dataset. Self-test an existing custom dataset here without modifying it.")}</p>
        {datasetPicker()}<button className="button secondary" disabled={!datasetId} onClick={() => void run(async () => { const value = await workerRequest<{ name: string; rows: unknown[] }>(`/intranet/datasets/${datasetId}`); setProbe(JSON.stringify({ ...value, benchmark: "custom" })); })}>{t("Load evaluator definition for self-test")}</button>
        {probe && <DatasetSelfTest key={datasetId} payload={probe} disabled={busy} />}
      </>}
      {tab === "Portable resources" && <>
        <p>{t("Portable v1 packages custom dataset definitions, exact baseline Git objects, prebuilt test images, selected Agent/runtime images, frozen contexts and company profiles in one ZIP. API credentials, run logs and future Git history are excluded.")}</p>
        <p className="wizard-notice">{t("Official SWE/CTX dataset bundles are not yet supported: their harnesses build additional dynamic environments. Use the standard dataset download guide and offline image export; do not assume those files alone make a standard suite offline-ready. Custom tasks must reference prebuilt images. LFS pointers and submodules are rejected with guidance.")}</p>
        <p>{t("Transfer directory inside Worker")}: <code>{inventory.transferDirectory || t("Connect the Worker to display its path.")}</code></p>
        {inventory.hostTransferDirectory && <p>{t("Transfer directory in WSL")}: <code>{inventory.hostTransferDirectory}</code>{distribution && inventory.hostTransferDirectory.startsWith("/") && <><br />{t("Windows Explorer path")}: <code>{`\\\\wsl.localhost\\${distribution}${inventory.hostTransferDirectory.replaceAll("/", "\\")}`}</code></>}</p>}
        <p>{t("Copy the ZIP between the host directories mounted at this Worker path on both computers. Do not paste a Windows path here. Install/start the destination Worker using the separate offline runtime package first.")}</p>
        <details open><summary>{t("Export benchmark resources")}</summary>{datasetPicker(true)}
          <p>{t('Export one case directly, or a dataset. The ZIP includes its definition, pinned baselines, required and selected images, and selected frozen context; runtime credentials must be configured separately on the destination.')}</p>
          <label>{t("Additional local image references (one per line)")}<textarea value={extraImages} onChange={(e) => setExtraImages(e.target.value)} /></label><p>{t("Task images are included automatically. Add your Agent image and any runtime images you also want to carry.")}</p>
          {inventory.profiles.map((p) => <label className="check-line" key={p.id}><input type="checkbox" checked={profileIds.includes(p.id)} onChange={() => setProfileIds(toggle(profileIds, p.id))} />{t("Include profile")}: {p.document.name} · {p.id.slice(0, 8)}</label>)}
          <button className="button secondary" onClick={() => void run(async () => { const value = await workerRequest<{ artifacts: KnowledgeArtifact[] }>("/snapshot?compact=true"); setContexts(value.artifacts); })}>{t("Load frozen context choices")}</button>
          {contexts.map((context) => <label className="check-line" key={context.id}><input type="checkbox" checked={contextIds.includes(context.id)} onChange={() => setContextIds(toggle(contextIds, context.id))} />{context.repository} @ {context.commit.slice(0, 8)} · {context.id.slice(0, 8)}</label>)}
          <label className="check-line"><input type="checkbox" checked={trustExport} onChange={(e) => setTrustExport(e.target.checked)} />{t("I have reviewed dataset contents, images and redistribution permissions. No secret scanner can guarantee that arbitrary image layers are safe to share.")}</label>
          <button className="button primary" disabled={!datasetId || !trustExport} onClick={() => void run(() => queue("bundle-export", { dataset: datasetId, images: namesFromLines(extraImages), contextIds, profileIds }))}>{t("Create portable resource ZIP")}</button>
        </details>
        <details><summary>{t("Inspect and import a resource ZIP")}</summary>
          <label>{t("ZIP filename in transfer directory")}<input value={filename} onChange={(e) => { setFilename(e.target.value); setInspection(undefined); setTrustImport(false); }} placeholder="ctxbench-resources-op-example.zip" /></label>
          <button className="button secondary" disabled={!filename} onClick={() => void run(async () => { setInspection(undefined); await queue("bundle-inspect", { filename }); })}>{t("Verify hashes, dependencies and conflicts")}</button>
          {inspection && <div><p>{inspection.dataset} · {t("Images")}: {inspection.images} · {t("Baselines")}: {inspection.baselines} · {t("Frozen contexts")}: {inspection.contexts}</p><p>SHA-256: <code>{inspection.sha256}</code></p><p>{t("Estimated free space required")}: {(inspection.requiredBytes / 1024 ** 3).toFixed(1)} GiB · {t("Available")}: {(inspection.freeBytes / 1024 ** 3).toFixed(1)} GiB</p>
            {inspection.conflicts.length > 0 && <p role="alert">{t("Conflicting image tags; existing images will not be overwritten.")}: {inspection.conflicts.join(", ")}</p>}
            <label className="check-line"><input type="checkbox" checked={trustImport} onChange={(e) => setTrustImport(e.target.checked)} />{t("I trust this resource bundle. Hashes detect corruption, not whether tests or images are safe.")}</label>
            <button className="button primary" disabled={!inspection.ready || !trustImport} onClick={() => void run(() => queue("bundle-import", { filename, expectedSha256: inspection.sha256, trusted: trustImport }))}>{t("Import verified resources")}</button>
          </div>}
        </details>
      </>}
    </fieldset>
    {busy && <p role="status">{t("Working… Large resource checks can take several minutes.")}</p>}
    {error && <p className="form-error" role="alert">{error}</p>}{message && <p role="status">{message}</p>}
    {job && <OperatorJobPanel initial={job} onCompleted={(completed) => { if (completed.result?.inspection?.filename === filename) setInspection(completed.result.inspection); }} />}
    {inventory.operations.length > 0 && <details><summary>{t("Recent operator operations")}</summary>{[...inventory.operations].reverse().map((item) => <button className="button secondary" key={item.id} onClick={() => setJob(item)}>{t(operatorKindLabel(item.kind))} · {t(item.status)} · {item.id}</button>)}</details>}
  </section>;
}
