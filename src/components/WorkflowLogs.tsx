import { useEffect, useState } from "react";
import { useI18n } from "../i18n";
import { workerRequest } from "../lib/desktop";
import { Modal } from "./WorkbenchDialogs";
import { FormError } from "./Dialogs";
import { ContainerLogViewer } from './ContainerLogs';

export function WorkflowLogs({ operationId, onClose }: { operationId: string; onClose: () => void }) {
  const { t } = useI18n();
  const [file, setFile] = useState("");
  const [content, setContent] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    if (!file) { setContent(''); setError(''); return; }
    setContent(t("Loading…")); setError("");
    void workerRequest<{ agentRunId?: string }>(`/operations/${operationId}`).then(async (operation) => {
      if (!operation.agentRunId) return t("No agent run has started yet.");
      const result = await workerRequest<{ content: string; hasMore: boolean }>(`/run-output?runId=${encodeURIComponent(operation.agentRunId)}&file=${encodeURIComponent(file)}`);
      return result.content + (result.hasMore ? `\n${t("Output truncated; full evidence remains in the worker run directory.")}` : "");
    }).then((value) => { if (active) setContent(value); }).catch((error) => { if (active) { setContent(""); setError(String(error)); } });
    return () => { active = false; };
  }, [operationId, file, refresh, t]);
  return <Modal title={t("Workflow logs")} onClose={onClose}>
    <ContainerLogViewer scope={{ operationId }} />
    <label>{t("Evidence")}<select value={file} onChange={(event) => setFile(event.target.value)}><option value="">{t('Select saved evidence (optional)')}</option>{["workflow.json", "setup.log", "trajectory.live.jsonl", "result.json", "agent.stderr.log", "container.log"].map((item) => <option key={item}>{item}</option>)}</select></label>
    {file && <button type="button" className="button secondary" onClick={() => setRefresh((value) => value + 1)}>{t("Refresh")}</button>}
    {error && <FormError>{error}</FormError>}
    {file && <pre className="log-view">{content}</pre>}
  </Modal>;
}
