import { ArchiveRestore, DatabaseZap, FileCode2, Fingerprint, Plus, RefreshCw, Search } from "lucide-react";
import { useMemo, useState } from "react";
import { PageTitle, ProgressBar, StatusBadge } from "../components/shared";
import type { DashboardSnapshot } from "../domain/types";
import { useI18n } from "../i18n";
import { bytes, relativeTime, titleCase } from "../lib/format";

export function KnowledgePage({ snapshot }: { snapshot: DashboardSnapshot }) {
  const { locale, t } = useI18n();
  const [query, setQuery] = useState("");
  const artifacts = useMemo(
    () => snapshot.artifacts.filter((artifact) => artifact.repository.toLowerCase().includes(query.toLowerCase())),
    [query, snapshot.artifacts],
  );
  const reuse = snapshot.artifacts.reduce((sum, artifact) => sum + artifact.tasksReused, 0);

  return (
    <div className="page">
      <PageTitle
        eyebrow={t("KNOWLEDGE ARTIFACTS")}
        title={t("Generate once. Measure repeatedly.")}
        description={t("Frozen repository context keyed by commit, builder configuration, prompt, and skill version.")}
        actions={
          <>
            <button className="button secondary"><ArchiveRestore size={16} /> {t("Import package")}</button>
            <button className="button primary"><Plus size={16} /> {t("Generate context")}</button>
          </>
        }
      />

      <section className="knowledge-summary">
        <div><DatabaseZap size={19} /><span>{t("Ready artifacts")}</span><strong>{snapshot.artifacts.filter((item) => item.status === "ready").length}</strong></div>
        <div><RefreshCw size={19} /><span>{t("Cross-task reuses")}</span><strong>{reuse}</strong></div>
        <div><FileCode2 size={19} /><span>{t("Context files")}</span><strong>{snapshot.artifacts.reduce((sum, item) => sum + item.files, 0)}</strong></div>
        <div><Fingerprint size={19} /><span>{t("Task-informed")}</span><strong>{snapshot.artifacts.filter((item) => item.informed).length}</strong></div>
      </section>

      <div className="toolbar">
        <label className="table-search"><Search size={15} /><input aria-label={t("Search repositories or commits")} value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t("Search repositories or commits")} /></label>
        <div className="toolbar-spacer" />
        <span className="cache-policy"><i /> {t("content-addressed cache")}</span>
      </div>

      <section className="artifact-grid">
        {artifacts.map((artifact) => (
          <article className="artifact-card" key={artifact.id}>
            <div className="artifact-top">
              <div className="repo-icon"><DatabaseZap size={18} /></div>
              <div><h3>{artifact.repository}</h3><code>{artifact.commit}</code></div>
              <StatusBadge status={artifact.status} />
            </div>
            {artifact.status === "generating" ? (
              <div className="generation-block">
                <div><span>{t("Inspecting architecture and conventions")}</span><strong>62%</strong></div>
                <ProgressBar value={0.62} />
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
                <div className="artifact-files"><FileCode2 size={14} /><span>AGENTS.md</span><span>.ctx/architecture.md</span><span>.ctx/conventions.md</span></div>
              </>
            )}
            <div className="artifact-footer">
              <span>{t("skill {version}", { version: artifact.skillVersion })}</span>
              <span>{t("prompt {hash}", { hash: artifact.promptHash })}</span>
              <time>{relativeTime(artifact.generatedAt, locale)}</time>
            </div>
          </article>
        ))}
      </section>

      <div className="causal-callout">
        <Fingerprint size={20} />
        <div><strong>{t("Passive context guarantee")}</strong><span>{t("Artifacts are overlaid as repository files only. CTXBench never changes the task prompt, forces reads, or adds retrieval hints.")}</span></div>
      </div>
    </div>
  );
}
