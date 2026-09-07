import { useCallback, useEffect, useState } from "react";
import { CheckCircle2, LoaderCircle, X } from "lucide-react";
import type { Page } from "./app-types";
import { ExperimentComposer } from "./components/ExperimentComposer";
import { DatasetWizard } from "./components/DatasetWizard";
import { DatasetDialog, PreparationDialog, RunDialog, PackageDialog } from "./components/WorkbenchDialogs";
import { Sidebar } from "./components/Sidebar";
import { Topbar } from "./components/Topbar";
import type { BenchmarkRun, CreateExperimentRequest, DashboardSnapshot, DiagnosticItem } from "./domain/types";
import { useI18n } from "./i18n";
import { createExperiment, diagnoseEnvironment, exportSnapshot, loadSnapshot, workerRequest } from "./lib/desktop";
import { ConstraintsPage } from "./pages/ConstraintsPage";
import { DashboardPage } from "./pages/DashboardPage";
import { ExperimentsPage } from "./pages/ExperimentsPage";
import { InfrastructurePage } from "./pages/InfrastructurePage";
import { KnowledgePage } from "./pages/KnowledgePage";

export default function App() {
  const { t } = useI18n();
  const [page, setPage] = useState<Page>("overview");
  const [snapshot, setSnapshot] = useState<DashboardSnapshot>();
  const [loadingError, setLoadingError] = useState<string>();
  const [modalOpen, setModalOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [diagnosing, setDiagnosing] = useState(false);
  const [diagnostics, setDiagnostics] = useState<DiagnosticItem[]>([]);
  const [toast, setToast] = useState<string>();
  const closeToast = useCallback(() => setToast(undefined), []);
  const [dialog, setDialog] = useState<"dataset" | "dataset-create" | "context" | "manual" | "constraints">();
  const [selectedRun, setSelectedRun] = useState<BenchmarkRun>();
  const [selectedPackage, setSelectedPackage] = useState<string>();
  const refresh = () => loadSnapshot().then((value) => { setSnapshot((old) => ({ ...value, diagnostics: old?.diagnostics ?? value.diagnostics })); setLoadingError(undefined); }).catch((error: unknown) => setLoadingError(error instanceof Error ? error.message : String(error)));

  useEffect(() => {
    let alive = true;
    let timer: number;
    const poll = async () => {
      try { const value = await loadSnapshot(); if (alive) { setSnapshot((old) => ({ ...value, diagnostics: old?.diagnostics ?? value.diagnostics })); setLoadingError(undefined); } }
      catch (error) { if (alive) setLoadingError(String(error)); }
      if (alive) timer = window.setTimeout(poll, 3000);
    };
    void poll();
    void diagnoseEnvironment().then((diagnostics) => { if (alive) setDiagnostics(diagnostics); }).catch(() => {});
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
      setPage("experiments");
      setToast(t("Experiment plan created. Context preparation is queued."));
    } catch (error) {
      throw error;
    } finally {
      setCreating(false);
    }
  };

  const handleDiagnose = async (distribution?: string) => {
    setDiagnosing(true);
    setSnapshot((current) => current ? { ...current, diagnostics: current.diagnostics.map((item) => ({ ...item, status: "checking" })) } : current);
    try {
      const diagnostics = await diagnoseEnvironment(distribution);
      setDiagnostics(diagnostics);
      setSnapshot((current) => current ? { ...current, diagnostics } : current);
      setToast(t("Environment diagnostics completed."));
    } catch (error) {
      setToast(String(error));
    } finally {
      setDiagnosing(false);
    }
  };

  if (loadingError && !snapshot) {
    return <div className="offline-shell"><Topbar runtime="desktop" /><div className="content-scroll"><p className="connection-banner" role="alert">{t("Worker disconnected")} · {t(loadingError)}</p><InfrastructurePage diagnostics={diagnostics} onDiagnose={(distribution) => { void handleDiagnose(distribution); void refresh(); }} diagnosing={diagnosing} /></div></div>;
  }
  if (!snapshot) {
    return <div className="splash"><div className="splash-mark">CX</div><LoaderCircle className="spin" size={20} /><span>{t("Opening local benchmark lab…")}</span></div>;
  }

  return (
    <div className="app-shell">
      <Sidebar page={page} onNavigate={setPage} />
      <main className="main-shell">
        <Topbar runtime={snapshot.runtime} />
        <div className="content-scroll">
          {loadingError && <p className="connection-banner" role="alert">{t("Worker disconnected — showing last received data")}</p>}
          {snapshot.runtime === "mock" && <p className="connection-banner">{t("Demo data — not benchmark results")}</p>}
          {page === "overview" && <DashboardPage snapshot={snapshot} onNewExperiment={() => setModalOpen(true)} onOpenExperiments={() => setPage("experiments")} onRun={setSelectedRun} />}
          {page === "experiments" && <ExperimentsPage snapshot={snapshot} onNewExperiment={() => setModalOpen(true)} onImport={() => setDialog("dataset")} onCreateDataset={() => setDialog("dataset-create")} onRun={setSelectedRun} onAction={(id, action) => { void workerRequest(`/experiments/${id}/${action}`, "POST").then(refresh).catch((error) => setToast(String(error))); }} onExport={(format) => { void exportSnapshot(snapshot, format).catch((error) => setToast(String(error))); }} />}
          {page === "knowledge" && <KnowledgePage snapshot={snapshot} onImport={() => setDialog("manual")} onGenerate={() => setDialog("context")} onView={setSelectedPackage} />}
          {page === "constraints" && <ConstraintsPage snapshot={snapshot} onMine={() => setDialog("constraints")} />}
          {page === "infrastructure" && <InfrastructurePage diagnostics={diagnostics} onDiagnose={handleDiagnose} diagnosing={diagnosing} />}
        </div>
      </main>
      {modalOpen && <ExperimentComposer creating={creating} onClose={() => setModalOpen(false)} onCreate={handleCreate} artifacts={snapshot.artifacts} />}
      {dialog === "dataset" && <DatasetDialog onClose={() => setDialog(undefined)} onComplete={() => void refresh()} />}
      {dialog === "dataset-create" && <DatasetWizard onClose={() => setDialog(undefined)} onComplete={() => void refresh()} />}
      {dialog && dialog !== "dataset" && dialog !== "dataset-create" && <PreparationDialog kind={dialog} onClose={() => setDialog(undefined)} onComplete={() => void refresh()} />}
      {selectedRun && <RunDialog run={snapshot.runs.find((run) => run.id === selectedRun.id) ?? selectedRun} onClose={() => setSelectedRun(undefined)} />}
      {selectedPackage && <PackageDialog id={selectedPackage} onClose={() => setSelectedPackage(undefined)} />}
      {toast && <Toast message={toast} onClose={closeToast} />}
    </div>
  );
}

function Toast({ message, onClose }: { message: string; onClose: () => void }) {
  const { t } = useI18n();
  useEffect(() => {
    const timer = window.setTimeout(onClose, 4_000);
    return () => window.clearTimeout(timer);
  }, [onClose]);
  return <div className="toast"><CheckCircle2 size={17} /><span>{message}</span><button onClick={onClose} aria-label={t("Close")}><X size={14} /></button></div>;
}
