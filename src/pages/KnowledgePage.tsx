import { ArchiveRestore, DatabaseZap, FileCode2, Fingerprint, Plus, RefreshCw, Search } from "lucide-react";
import { useMemo, useState } from "react";
import { PageTitle, ProgressBar, StatusBadge } from "../components/shared";
import type { DashboardSnapshot } from "../domain/types";
import { useI18n } from "../i18n";
import { bytes, relativeTime, titleCase } from "../lib/format";
import { PreparationQueue } from "../components/PreparationQueue";
import { Pagination } from "../components/Pagination";
import { pageWindow } from "../domain/pagination";

export function KnowledgePage({ snapshot, onImport, onGenerate, onView }: { snapshot: DashboardSnapshot; onImport: () => void; onGenerate: () => void; onView: (id: string) => void }) {
  const { locale, t } = useI18n();
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);
  const artifacts = useMemo(
    () => snapshot.artifacts.filter((artifact) => `${artifact.repository} ${artifact.commit}`.toLowerCase().includes(query.toLowerCase())),
    [query, snapshot.artifacts],
  );
  const reuse = snapshot.artifacts.reduce((sum, artifact) => sum + artifact.tasksReused, 0);
  const window = pageWindow(artifacts.length, page, 20);

  return (
    <div className="page">
      <PageTitle
        eyebrow={t("KNOWLEDGE ARTIFACTS")}
        title={t("Generate once. Measure repeatedly.")}
        description={t("Frozen repository context keyed by commit, builder configuration, prompt, and skill version.")}
        actions={
          <>
            <button className="button secondary" onClick={onImport}><ArchiveRestore size={16} /> {t("Import package")}</button>
            <button className="button primary" onClick={onGenerate}><Plus size={16} /> {t("Generate context")}</button>
          </>
        }
      />

      <section className="knowledge-summary">
        <div><DatabaseZap size={19} /><span>{t("Ready artifacts")}</span><strong>{snapshot.artifacts.filter((item) => item.status === "ready").length}</strong></div>
        <div><RefreshCw size={19} /><span>{t("Artifact-backed runs")}</span><strong>{reuse}</strong></div>
        <div><FileCode2 size={19} /><span>{t("Context files")}</span><strong>{snapshot.artifacts.reduce((sum, item) => sum + item.files, 0)}</strong></div>
        <div><Fingerprint size={19} /><span>{t("Task-informed")}</span><strong>{snapshot.artifacts.filter((item) => item.informed).length}</strong></div>
      </section>
      <PreparationQueue operations={snapshot.operations ?? []} kind="context" />

      <div className="toolbar">
        <label className="table-search"><Search size={15} /><input aria-label={t("Search repositories or commits")} value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t("Search repositories or commits")} /></label>
        <div className="toolbar-spacer" />
        <span className="cache-policy"><i /> {t("content-addressed cache")}</span>
      </div>

      <section className="artifact-grid">
        {artifacts.slice(window.start, window.end).map((artifact) => (
          <article className="artifact-card" key={artifact.id}>
            <div className="artifact-top">
              <div className="repo-icon"><DatabaseZap size={18} /></div>
              <div><h3>{t(artifact.repository)}</h3><code>{artifact.status === "invalid" ? artifact.id : artifact.commit}</code></div>
              <StatusBadge status={artifact.status} />
            </div>
            {artifact.status === "invalid" ? <p role="alert" className="form-error">{artifact.failure}</p> : artifact.status === "generating" ? (
              <div className="generation-block">
                <div><span>{t("Inspecting architecture and conventions")}</span></div>
                <small>{t("Builder isolated · target task hidden")}</small>
              </div>
            ) : (
              <>
                <div className="artifact-facts">
                  <div><span>{t("Source")}</span><strong>{t(titleCase(artifact.source))}</strong></div>
                  <div><span>{t("Capability")}</span><strong>{t(titleCase(artifact.capability))}</strong></div>
                  <div><span>{t("Payload")}</span><strong>{t("{count} files · {size}", { count: artifact.files, size: bytes(artifact.bytes) })}</strong></div>
                  <div><span>{t("Reused")}</span><strong>{t("{count} runs", { count: artifact.tasksReused })}</strong></div>
                </div>
                <div className="artifact-files"><FileCode2 size={14} />{artifact.filePaths?.map((path) => <span key={path}>{path}</span>)}</div>
              </>
            )}
            <div className="artifact-footer">
              <button className="text-button" disabled={artifact.status !== "ready"} onClick={() => onView(artifact.id)}>{t("View package")}</button>
              <span title={artifact.skillVersion}>{t("skill {version}", { version: artifact.skillVersion.slice(0, 12) })}</span>
              <span title={artifact.promptHash}>{t("prompt {hash}", { hash: artifact.promptHash.slice(0, 12) })}</span>
              <time>{relativeTime(artifact.generatedAt, locale)}</time>
            </div>
          </article>
        ))}
      </section>
      <Pagination total={artifacts.length} page={page} size={20} onChange={setPage} />
      <div className="causal-callout">
        <Fingerprint size={20} />
        <div><strong>{t("Passive context guarantee")}</strong><span>{t("Artifacts are overlaid as repository files only. CTXBench never changes the task prompt, forces reads, or adds retrieval hints.")}</span></div>
      </div>
    </div>
  );
}
