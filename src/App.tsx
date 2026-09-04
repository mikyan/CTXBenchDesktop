import { useEffect, useState } from "react";
import { CheckCircle2, LoaderCircle, X } from "lucide-react";
import type { Page } from "./app-types";
import { NewExperimentModal } from "./components/NewExperimentModal";
import { Sidebar } from "./components/Sidebar";
import { Topbar } from "./components/Topbar";
import type { CreateExperimentRequest, DashboardSnapshot, Experiment } from "./domain/types";
import { createExperiment, diagnoseEnvironment, exportSnapshot, loadSnapshot } from "./lib/desktop";
import { ConstraintsPage } from "./pages/ConstraintsPage";
import { DashboardPage } from "./pages/DashboardPage";
import { ExperimentsPage } from "./pages/ExperimentsPage";
import { InfrastructurePage } from "./pages/InfrastructurePage";
import { KnowledgePage } from "./pages/KnowledgePage";

export default function App() {
  const [page, setPage] = useState<Page>("overview");
  const [snapshot, setSnapshot] = useState<DashboardSnapshot>();
  const [loadingError, setLoadingError] = useState<string>();
  const [modalOpen, setModalOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [diagnosing, setDiagnosing] = useState(false);
  const [toast, setToast] = useState<string>();

  useEffect(() => {
    loadSnapshot().then(setSnapshot).catch((error: unknown) => setLoadingError(error instanceof Error ? error.message : String(error)));
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
      setToast("Experiment plan created. Context preparation is queued.");
    } catch (error) {
      setToast(error instanceof Error ? error.message : String(error));
    } finally {
      setCreating(false);
    }
  };

  const handleDiagnose = async () => {
    setDiagnosing(true);
    setSnapshot((current) => current ? { ...current, diagnostics: current.diagnostics.map((item) => ({ ...item, status: "checking" })) } : current);
    try {
      const diagnostics = await diagnoseEnvironment();
      setSnapshot((current) => current ? { ...current, diagnostics } : current);
      setToast("Environment diagnostics completed.");
    } finally {
      setDiagnosing(false);
    }
  };

  if (loadingError) {
    return <div className="fatal-state"><X size={28} /><h1>Could not start CTXBench</h1><p>{loadingError}</p><button className="button primary" onClick={() => window.location.reload()}>Retry</button></div>;
  }
  if (!snapshot) {
    return <div className="splash"><div className="splash-mark">CX</div><LoaderCircle className="spin" size={20} /><span>Opening local benchmark lab…</span></div>;
  }

  return (
    <div className="app-shell">
      <Sidebar page={page} onNavigate={setPage} />
      <main className="main-shell">
        <Topbar runtime={snapshot.runtime} />
        <div className="content-scroll">
          {page === "overview" && <DashboardPage snapshot={snapshot} onNewExperiment={() => setModalOpen(true)} onOpenExperiments={() => setPage("experiments")} />}
          {page === "experiments" && <ExperimentsPage snapshot={snapshot} onNewExperiment={() => setModalOpen(true)} onExport={(format) => exportSnapshot(snapshot, format)} />}
          {page === "knowledge" && <KnowledgePage snapshot={snapshot} />}
          {page === "constraints" && <ConstraintsPage snapshot={snapshot} />}
          {page === "infrastructure" && <InfrastructurePage diagnostics={snapshot.diagnostics} onDiagnose={handleDiagnose} diagnosing={diagnosing} />}
        </div>
      </main>
      <NewExperimentModal open={modalOpen} creating={creating} onClose={() => setModalOpen(false)} onCreate={handleCreate} />
      {toast && <Toast message={toast} onClose={() => setToast(undefined)} />}
    </div>
  );
}

function Toast({ message, onClose }: { message: string; onClose: () => void }) {
  useEffect(() => {
    const timer = window.setTimeout(onClose, 4_000);
    return () => window.clearTimeout(timer);
  }, [onClose]);
  return <div className="toast"><CheckCircle2 size={17} /><span>{message}</span><button onClick={onClose}><X size={14} /></button></div>;
}
