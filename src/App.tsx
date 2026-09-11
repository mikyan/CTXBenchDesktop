import { useCallback, useEffect, useRef, useState } from "react";
import { CheckCircle2, CircleAlert, LoaderCircle, X } from "lucide-react";
import type { Page } from "./app-types";
import { ExperimentComposer } from "./components/ExperimentComposer";
import { DatasetDialog, PreparationDialog, RunDialog, PackageDialog } from "./components/WorkbenchDialogs";
import { Sidebar } from "./components/Sidebar";
import { Topbar } from "./components/Topbar";
import type { BenchmarkKind, BenchmarkRun, CreateExperimentRequest, DashboardSnapshot, DiagnosticItem } from "./domain/types";
import { useI18n } from "./i18n";
import { createExperiment, diagnoseEnvironment, exportSnapshot, loadSnapshot, workerRequest } from "./lib/desktop";
import { ConstraintsPage } from "./pages/ConstraintsPage";
import { DashboardPage } from "./pages/DashboardPage";
import { ExperimentsPage } from "./pages/ExperimentsPage";
import { InfrastructurePage } from "./pages/InfrastructurePage";
import { KnowledgePage } from "./pages/KnowledgePage";
import { DatasetsPage } from "./pages/DatasetsPage";

export default function App() {
  const { t } = useI18n();
  const [page, setPage] = useState<Page>("overview");
  const [settingsSection, setSettingsSection] = useState<"runtime" | "images">("runtime");
  const [snapshot, setSnapshot] = useState<DashboardSnapshot>();
  const [loadingError, setLoadingError] = useState<string>();
  const [modalOpen, setModalOpen] = useState(false);
  const [initialDataset, setInitialDataset] = useState("");
  const [imageSelection, setImageSelection] = useState<import("./lib/standard-images").ImageSelection>();
  const [experimentRevision, setExperimentRevision] = useState(0);
  const [initialBenchmark, setInitialBenchmark] = useState<BenchmarkKind | "">("");
  const [importSource, setImportSource] = useState<BenchmarkKind>("ctxbench");
  const contentRef = useRef<HTMLDivElement>(null);
  const openExperiment = (dataset = "", selection?: import("./lib/standard-images").ImageSelection) => { setInitialDataset(dataset); setImageSelection(selection); setModalOpen(true); };
  useEffect(() => { contentRef.current?.scrollTo({ top: 0 }); }, [page]);
  const [creating, setCreating] = useState(false);
  const [diagnosing, setDiagnosing] = useState(false);
  const [diagnostics, setDiagnostics] = useState<DiagnosticItem[]>([]);
  const diagnosticRevision = useRef(0);
  const [toast, setToast] = useState<{ message: string; error?: boolean }>();
  const closeToast = useCallback(() => setToast(undefined), []);
  const [dialog, setDialog] = useState<"dataset" | "context" | "manual" | "constraints">();
  const [preparationSource, setPreparationSource] = useState('');
  const [selectedRun, setSelectedRun] = useState<BenchmarkRun>();
  const [selectedPackage, setSelectedPackage] = useState<string>();
  const refresh = () => loadSnapshot().then((value) => { setSnapshot((old) => ({ ...value, diagnostics: old?.diagnostics ?? value.diagnostics })); setLoadingError(undefined); }).catch((error: unknown) => setLoadingError(error instanceof Error ? error.message : String(error)));

  useEffect(() => {
    let alive = true;
    let timer: number;
    const poll = async () => {
      try { const value = await loadSnapshot(); if (alive) { setSnapshot((old) => ({ ...value, diagnostics: old?.diagnostics ?? value.diagnostics })); setLoadingError(undefined); } }
      catch (error) { if (alive) setLoadingError(error instanceof Error ? error.message : String(error)); }
      if (alive) timer = window.setTimeout(poll, 3000);
    };
    void poll();
    const revision = ++diagnosticRevision.current;
    void diagnoseEnvironment().then((diagnostics) => { if (alive && revision === diagnosticRevision.current) setDiagnostics(diagnostics); }).catch(() => {});
    return () => { alive = false; window.clearTimeout(timer); };
  }, []);

  useEffect(() => {
    if (!snapshot || snapshot.runtime !== "mock") return;
    const timer = window.setInterval(() => {
      setSnapshot((current) => {
        if (!current) return current;
        const experiments = current.experiments.map((experiment, index) => {
          if (index !== 0 || experiment.status !== "running" || experiment.completedRuns >= experiment.totalRuns) return experiment;
          return { ...experiment, completedRuns: Math.min(experiment.totalRuns, experiment.completedRuns + 1), updatedAt: new Date().toISOString() };
        });
        return { ...current, experiments };
      });
    }, 4_000);
    return () => window.clearInterval(timer);
  }, [snapshot?.runtime]);

  const handleCreate = async (request: CreateExperimentRequest) => {
    setCreating(true);
    try {
      const experiment = await createExperiment(request);
      setSnapshot((current) => current ? { ...current, experiments: [experiment, ...current.experiments] } : current);
      setModalOpen(false);
      setInitialBenchmark("");
      setExperimentRevision((value) => value + 1);
      setPage("experiments");
      setToast({ message: t("Experiment plan created. Context preparation is queued.") });
    } catch (error) {
      throw error;
    } finally {
      setCreating(false);
    }
  };

  const handleDiagnose = async (distribution?: string) => {
    const revision = ++diagnosticRevision.current;
    setDiagnosing(true);
    setSnapshot((current) => current ? { ...current, diagnostics: current.diagnostics.map((item) => ({ ...item, status: "checking" })) } : current);
    try {
      const diagnostics = await diagnoseEnvironment(distribution);
      if (revision !== diagnosticRevision.current) return;
      setDiagnostics(diagnostics);
      setSnapshot((current) => current ? { ...current, diagnostics } : current);
      const attention = diagnostics.filter((item) => item.status !== "healthy").length;
      setToast(attention ? { message: t("Diagnostics finished. Checks needing attention: {count}. Follow the guidance on this page.", { count: attention }), error: true } : { message: t("Environment diagnostics completed.") });
    } catch (error) {
      if (revision === diagnosticRevision.current) setToast({ message: String(error), error: true });
    } finally {
      if (revision === diagnosticRevision.current) setDiagnosing(false);
    }
  };

  if (loadingError && !snapshot) {
    return <div className="offline-shell"><Topbar runtime="desktop" /><div className="content-scroll"><p className="connection-banner" role="alert">{t("Worker disconnected")} · {t(loadingError)}</p><InfrastructurePage diagnostics={diagnostics} onDiagnose={(distribution) => { void handleDiagnose(distribution); void refresh(); }} diagnosing={diagnosing} /></div>{toast && <Toast {...toast} onClose={closeToast} />}</div>;
  }
  if (!snapshot) {
    return <div className="splash"><div className="splash-mark">CX</div><LoaderCircle className="spin" size={20} /><span>{t("Opening local benchmark lab…")}</span></div>;
  }

  return (
    <div className="app-shell">
      <Sidebar page={page} onNavigate={setPage} />
      <main className="main-shell">
        <Topbar runtime={snapshot.runtime} page={page} />
        <div className="content-scroll" ref={contentRef}>
          {loadingError && <p className="connection-banner" role="alert">{t("Worker disconnected — showing last received data")}</p>}
          {snapshot.runtime === "mock" && <p className="connection-banner">{t("Demo data — not benchmark results")}</p>}
          {page === "overview" && <DashboardPage snapshot={snapshot} onNewExperiment={() => openExperiment()} onOpenExperiments={(benchmark) => { setInitialBenchmark(benchmark ?? ""); setPage("experiments"); }} onRun={setSelectedRun} />}
          {page === "experiments" && <ExperimentsPage key={experimentRevision} snapshot={snapshot} initialBenchmark={initialBenchmark} onNewExperiment={() => openExperiment()} onDatasets={() => setPage("datasets")} onRun={setSelectedRun} onDeleted={() => { void refresh(); }} onAction={(id, action) => { void workerRequest(`/experiments/${id}/${action}`, "POST").then(refresh).catch((error) => setToast({ message: String(error), error: true })); }} onExport={(format) => { void exportSnapshot(snapshot, format).catch((error) => setToast({ message: String(error), error: true })); }} />}
          {(page === "datasets" || page === "cases") && <DatasetsPage key={page} initialView={page === 'cases' ? 'cases' : 'sets'} snapshot={snapshot} onImport={(source) => { setImportSource(source ?? "ctxbench"); setDialog("dataset"); }} onExperiment={openExperiment} onGenerate={(source) => { setPreparationSource(source); setDialog('context'); }} />}
          {page === "knowledge" && <KnowledgePage snapshot={snapshot} onImport={() => { setPreparationSource(''); setDialog("manual"); }} onGenerate={() => { setPreparationSource(''); setDialog("context"); }} onView={setSelectedPackage} />}
          {page === "constraints" && <ConstraintsPage snapshot={snapshot} onMine={() => setDialog("constraints")} />}
          {page === "infrastructure" && <InfrastructurePage initialSection={settingsSection} diagnostics={diagnostics} onDiagnose={handleDiagnose} diagnosing={diagnosing} onExperiments={() => setPage("experiments")} onKnowledge={() => setPage("knowledge")} />}
        </div>
      </main>
      {modalOpen && <ExperimentComposer initialDataset={initialDataset} imageSelection={imageSelection} creating={creating} onClose={() => setModalOpen(false)} onCreate={handleCreate} artifacts={snapshot.artifacts} artifactLoadError={Boolean(loadingError)} onRefreshArtifacts={refresh} />}
      {dialog === "dataset" && <DatasetDialog initialBenchmark={importSource} onClose={() => setDialog(undefined)} onComplete={() => void refresh()} onSettings={(section) => { setDialog(undefined); setSettingsSection(section); setPage("infrastructure"); }} />}
      {dialog && dialog !== "dataset" && <PreparationDialog kind={dialog} initialSource={dialog === 'constraints' ? '' : preparationSource} onClose={() => setDialog(undefined)} onComplete={() => void refresh()} />}
      {selectedRun && <RunDialog run={snapshot.runs.find((run) => run.id === selectedRun.id) ?? selectedRun} onClose={() => setSelectedRun(undefined)} onDeleted={() => { setSelectedRun(undefined); void refresh(); }} />}
      {selectedPackage && <PackageDialog id={selectedPackage} onClose={() => setSelectedPackage(undefined)} />}
      {toast && <Toast {...toast} onClose={closeToast} />}
    </div>
  );
}

function Toast({ message, error = false, onClose }: { message: string; error?: boolean; onClose: () => void }) {
  const { t } = useI18n();
  useEffect(() => {
    if (error) return; // Keep failures readable until the user dismisses them.
    const timer = window.setTimeout(onClose, 6_000);
    return () => window.clearTimeout(timer);
  }, [onClose, message, error]);
  return <div className={`toast ${error ? "error" : "success"}`} role={error ? "alert" : "status"}>{error ? <CircleAlert size={20} /> : <CheckCircle2 size={20} />}<span>{t(message)}</span><button onClick={onClose} aria-label={t("Close")}><X size={18} /></button></div>;
}
