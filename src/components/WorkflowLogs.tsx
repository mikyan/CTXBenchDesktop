import { useEffect, useState } from "react";
import { useI18n } from "../i18n";
import { workerRequest } from "../lib/desktop";
import { Modal } from "./WorkbenchDialogs";

export function WorkflowLogs({ operationId, onClose }: { operationId: string; onClose: () => void }) {
  const { t } = useI18n();
  const [file, setFile] = useState("workflow.json");
  const [content, setContent] = useState("");
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    let active = true;
    setContent(t("Loading…"));
    void workerRequest<{ agentRunId?: string }>(`/operations/${operationId}`).then(async (operation) => {
      if (!operation.agentRunId) return t("No agent run has started yet.");
      const result = await workerRequest<{ content: string; hasMore: boolean }>(`/run-output?runId=${encodeURIComponent(operation.agentRunId)}&file=${encodeURIComponent(file)}`);
      return result.content + (result.hasMore ? `\n${t("Output truncated; full evidence remains in the worker run directory.")}` : "");
    }).then((value) => { if (active) setContent(value); }).catch((error) => { if (active) setContent(String(error)); });
    return () => { active = false; };
  }, [operationId, file, refresh, t]);
  return <Modal title={t("Workflow logs")} onClose={onClose}>
    <label>{t("Evidence")}<select value={file} onChange={(event) => setFile(event.target.value)}>{["workflow.json", "setup.log", "trajectory.live.jsonl", "result.json", "agent.stderr.log"].map((item) => <option key={item}>{item}</option>)}</select></label>
    <button type="button" className="button secondary" onClick={() => setRefresh((value) => value + 1)}>{t("Refresh")}</button>
    <pre className="log-view">{content}</pre>
  </Modal>;
}
