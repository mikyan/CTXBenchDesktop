import { useEffect, useState } from "react";
import { ArrowRight, Download, LibraryBig, Plus, Search } from "lucide-react";
import type { BenchmarkKind, DashboardSnapshot, TaskSummary } from "../domain/types";
import { useI18n } from "../i18n";
import { workerRequest } from "../lib/desktop";
import { benchmarkLabel, datasetLabel } from "../lib/benchmark-labels";
import { pageWindow } from "../domain/pagination";
import { PageTitle } from "../components/shared";
import { Pagination } from "../components/Pagination";
import { SectionNav } from "../components/SectionNav";
import { StandardDatasetDownloads } from "../components/StandardDatasetDownloads";
import { IntranetWorkbench } from "../components/IntranetWorkbench";
import { StandardImageInstaller } from "../components/StandardImageInstaller";

const views = [{ id: "library", label: "Registered datasets" }, { id: "downloads", label: "Standard downloads" }, { id: "self-test", label: "Self-test" }] as const;
export function DatasetsPage({ snapshot, onImport, onCreate, onExperiment }: { snapshot: DashboardSnapshot; onImport: (source?: BenchmarkKind) => void; onCreate: () => void; onExperiment: (dataset: string) => void }) {
  const { t } = useI18n();
  const [view, setView] = useState<typeof views[number]["id"]>("library");
  const [installDataset, setInstallDataset] = useState<{ id: string; name: string }>();
  const [query, setQuery] = useState(""); const [selected, setSelected] = useState("");
  const [tasks, setTasks] = useState<TaskSummary[]>([]); const [loading, setLoading] = useState(false); const [error, setError] = useState("");
  const [taskQuery, setTaskQuery] = useState(""); const [page, setPage] = useState(0);
  const datasets = (snapshot.datasets ?? []).filter((row) => `${row.name} ${benchmarkLabel(row.benchmark, t)}`.toLowerCase().includes(query.toLowerCase()));
  useEffect(() => { let alive = true; setTasks([]); setError(""); setTaskQuery(""); setPage(0); setLoading(Boolean(selected));
    if (selected) void workerRequest<TaskSummary[]>(`/datasets/${selected}/tasks`).then((rows) => { if (alive) setTasks(rows); }).catch((cause) => { if (alive) setError(String(cause)); }).finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [selected]);
  const visibleTasks = tasks.filter((task) => `${task.id} ${task.repository}`.toLowerCase().includes(taskQuery.toLowerCase()));
  const range = pageWindow(visibleTasks.length, page, 20);
  return <div className="page datasets-page">
    <PageTitle eyebrow={t("DATASET LIBRARY")} title={t("Datasets")} description={t("Import standard suites or design custom tasks. Definitions stay frozen; hidden tests and reference patches remain evaluator-only.")} actions={<><button className="button secondary" onClick={() => onImport()}><Download size={16} />{t("Import dataset")}</button><button className="button primary" onClick={onCreate}><Plus size={16} />{t("Create dataset")}</button></>} />
    <SectionNav label="Dataset views" items={views} value={view} onChange={setView} />
    <div hidden={view !== "library"} className="settings-stack">
      <div className="toolbar"><label className="table-search"><Search size={16} /><input aria-label={t("Search datasets")} placeholder={t("Search datasets")} value={query} onChange={(e) => setQuery(e.target.value)} /></label></div>
      {!datasets.length && <div className="panel empty-state"><LibraryBig size={28} /><h2>{t(snapshot.datasets?.length ? "No matching datasets" : "No datasets yet")}</h2><p>{t(snapshot.datasets?.length ? "Try a different dataset name or clear the search." : "Import an official snapshot, or use the guided creator to build your own dataset.")}</p>{snapshot.datasets?.length ? <button className="button secondary" onClick={() => setQuery("")}>{t("Clear")}</button> : <button className="button secondary" onClick={() => setView("downloads")}>{t("Standard downloads")}</button>}</div>}
      <div className="dataset-library">{datasets.map((dataset) => <article className={`panel dataset-card ${selected === dataset.id ? "selected" : ""}`} key={dataset.id}>
        <span className="panel-kicker">{benchmarkLabel(dataset.benchmark, t)}</span><h2>{datasetLabel(dataset, t)}</h2><p>{dataset.count} {t("Tasks")} · {t("Frozen definition")}</p><code>{dataset.id}</code>
        <div className="form-actions"><button className="button secondary" aria-pressed={selected === dataset.id} onClick={() => setSelected(dataset.id)}>{t("Browse tasks")}</button>{dataset.benchmark !== "custom" && <button className="button secondary" onClick={() => setInstallDataset(dataset)}>{t("Install project images")}</button>}<button className="text-button" onClick={() => onExperiment(dataset.id)}>{t("New experiment")}<ArrowRight size={16} /></button></div>
      </article>)}</div>
      {selected && <section className="panel task-library"><div className="panel-header"><h2>{snapshot.datasets?.find((row) => row.id === selected)?.name} · {t("Tasks")}</h2></div>
        <label className="table-search"><Search size={16} /><input aria-label={t("Filter tasks")} placeholder={t("Filter tasks")} value={taskQuery} onChange={(e) => { setTaskQuery(e.target.value); setPage(0); }} /></label>
        {loading && <p role="status">{t("Loading…")}</p>}{error && <p className="form-error" role="alert">{error}</p>}
        {visibleTasks.slice(range.start, range.end).map((task) => <details key={task.id}><summary>{task.id}<small>{task.repository} · {task.baseCommit.slice(0, 12)}</small></summary><p className="task-prompt">{task.prompt}</p></details>)}
        <Pagination total={visibleTasks.length} page={page} size={20} onChange={setPage} />
      </section>}
    </div>
    <div hidden={view !== "downloads"}><StandardDatasetDownloads benchmark="custom" onSelect={onImport} /></div>
    <div hidden={view !== "self-test"}><IntranetWorkbench section="Dataset self-test" /></div>
    {installDataset && <StandardImageInstaller dataset={installDataset.id} name={installDataset.name} onClose={() => setInstallDataset(undefined)} />}
  </div>;
}
