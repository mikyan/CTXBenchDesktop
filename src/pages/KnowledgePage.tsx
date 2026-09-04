import { ArchiveRestore, DatabaseZap, FileCode2, Fingerprint, Plus, RefreshCw, Search } from "lucide-react";
import { useMemo, useState } from "react";
import { PageTitle, ProgressBar, StatusBadge } from "../components/shared";
import type { DashboardSnapshot } from "../domain/types";
import { bytes, relativeTime, titleCase } from "../lib/format";

export function KnowledgePage({ snapshot }: { snapshot: DashboardSnapshot }) {
  const [query, setQuery] = useState("");
  const artifacts = useMemo(
    () => snapshot.artifacts.filter((artifact) => artifact.repository.toLowerCase().includes(query.toLowerCase())),
    [query, snapshot.artifacts],
  );
  const reuse = snapshot.artifacts.reduce((sum, artifact) => sum + artifact.tasksReused, 0);

  return (
    <div className="page">
      <PageTitle
        eyebrow="KNOWLEDGE ARTIFACTS"
        title="Generate once. Measure repeatedly."
        description="Frozen repository context keyed by commit, builder configuration, prompt, and skill version."
        actions={
          <>
            <button className="button secondary"><ArchiveRestore size={16} /> Import package</button>
            <button className="button primary"><Plus size={16} /> Generate context</button>
          </>
        }
      />

      <section className="knowledge-summary">
        <div><DatabaseZap size={19} /><span>Ready artifacts</span><strong>{snapshot.artifacts.filter((item) => item.status === "ready").length}</strong></div>
        <div><RefreshCw size={19} /><span>Cross-task reuses</span><strong>{reuse}</strong></div>
        <div><FileCode2 size={19} /><span>Context files</span><strong>{snapshot.artifacts.reduce((sum, item) => sum + item.files, 0)}</strong></div>
        <div><Fingerprint size={19} /><span>Task-informed</span><strong>{snapshot.artifacts.filter((item) => item.informed).length}</strong></div>
      </section>

      <div className="toolbar">
        <label className="table-search"><Search size={15} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search repositories or commits" /></label>
        <div className="toolbar-spacer" />
        <span className="cache-policy"><i /> content-addressed cache</span>
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
                <div><span>Inspecting architecture and conventions</span><strong>62%</strong></div>
                <ProgressBar value={0.62} />
                <small>Builder isolated · target task hidden</small>
              </div>
            ) : (
              <>
                <div className="artifact-facts">
                  <div><span>Source</span><strong>{titleCase(artifact.source)}</strong></div>
                  <div><span>Capability</span><strong>{titleCase(artifact.capability)}</strong></div>
                  <div><span>Payload</span><strong>{artifact.files} files · {bytes(artifact.bytes)}</strong></div>
                  <div><span>Reused</span><strong>{artifact.tasksReused} runs</strong></div>
                </div>
                <div className="artifact-files"><FileCode2 size={14} /><span>AGENTS.md</span><span>.ctx/architecture.md</span><span>.ctx/conventions.md</span></div>
              </>
            )}
            <div className="artifact-footer">
              <span>skill {artifact.skillVersion}</span>
              <span>prompt {artifact.promptHash}</span>
              <time>{relativeTime(artifact.generatedAt)}</time>
            </div>
          </article>
        ))}
      </section>

      <div className="causal-callout">
        <Fingerprint size={20} />
        <div><strong>Passive context guarantee</strong><span>Artifacts are overlaid as repository files only. CTXBench never changes the task prompt, forces reads, or adds retrieval hints.</span></div>
      </div>
    </div>
  );
}
