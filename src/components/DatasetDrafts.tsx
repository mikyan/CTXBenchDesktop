import { useEffect, useState } from "react";
import { useI18n } from "../i18n";
import { saveText, workerRequest } from "../lib/desktop";
import { draftSchema, draftFromManifest, draftDifference, newDatasetDraft, type CustomTaskManifest, type DatasetDraft } from "../lib/dataset-authoring";
import type { DatasetRecord } from "../domain/types";
import type { IntranetInventory } from "../lib/intranet";
import { ConfirmDialog, FormError } from "./Dialogs";

export function DatasetDrafts({ draft, onLoad, disabled, onBusy }: { draft: DatasetDraft; onLoad: (draft: DatasetDraft) => void; disabled: boolean; onBusy?: (busy: boolean) => void }) {
  const { t } = useI18n();
  const [rows, setRows] = useState<IntranetInventory["drafts"]>([]); const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false); const [message, setMessage] = useState("");
  const [datasets, setDatasets] = useState<DatasetRecord[]>([]); const [dataset, setDataset] = useState("");
  const [baseline, setBaseline] = useState<DatasetDraft>();
  const [pending, setPending] = useState<DatasetDraft>(); const [error, setError] = useState("");
  const apply = (next: DatasetDraft) => { setBaseline(next); onLoad(next); setPending(undefined); };
  const replace = (next: DatasetDraft) => {
    if (JSON.stringify(draft) === JSON.stringify(newDatasetDraft()) || JSON.stringify(draft) === JSON.stringify(next)) apply(next);
    else setPending(next);
  };
  const changes = baseline ? draftDifference(baseline, draft) : undefined;
  useEffect(() => { let alive = true; void workerRequest<IntranetInventory>("/intranet").then((value) => { if (alive) setRows(value.drafts); }).catch(() => {}); return () => { alive = false; }; }, []);
  useEffect(() => { let alive = true; void workerRequest<DatasetRecord[]>("/datasets").then((value) => { if (alive) setDatasets(value.filter((d) => d.benchmark === "custom")); }).catch(() => {}); return () => { alive = false; }; }, []);
  const action = async (kind: "save" | "load" | "export" | "copy") => {
    setBusy(true); onBusy?.(true); setMessage(""); setError("");
    try {
      if (kind === "save") {
        const row = await workerRequest<IntranetInventory["drafts"][number]>("/intranet/drafts", "POST", draft);
        setRows((current) => [...current.filter((r) => r.id !== row.id), row]); setKey(row.id); setMessage(t("Draft version saved in the Worker. Existing datasets are unchanged."));
      } else if (kind === "load") {
        const row = await workerRequest<{ document: unknown }>(`/intranet/drafts/${key}`); replace(draftSchema.parse(row.document));
      } else if (kind === "copy") {
        const definition = await workerRequest<{ name: string; rows: CustomTaskManifest[] }>(`/intranet/datasets/${dataset}`);
        replace(draftFromManifest(definition.name, definition.rows));
      } else await saveText("ctxbench-dataset-draft.json", JSON.stringify(draft, null, 2));
    } catch (cause) { setError(String(cause)); } finally { setBusy(false); onBusy?.(false); }
  };
  const upload = async (file?: File) => {
    if (!file) return; setBusy(true); onBusy?.(true); setMessage(""); setError("");
    try { if (file.size > 10_000_000) throw Error("Draft files are limited to 10 MB."); replace(draftSchema.parse(JSON.parse(await file.text()))); }
    catch (cause) { setError(String(cause)); } finally { setBusy(false); onBusy?.(false); }
  };
  return <details className="dataset-drafts"><summary>{t("Save or restore a dataset draft")}</summary><fieldset disabled={disabled || busy}>
    <p>{t("Drafts may contain hidden tests and reference fixes. They stay in the evaluator workspace, not browser storage. Loading replaces the current unsaved draft.")}</p>
    <div className="wizard-actions"><button className="button secondary" onClick={() => void action("save")}>{t("Save draft version")}</button><button className="button secondary" onClick={() => void action("export")}>{t("Export draft JSON")}</button></div>
    <label>{t("Saved draft versions")}<select value={key} onChange={(e) => setKey(e.target.value)}><option value="">{t("Choose a saved draft")}</option>{rows.map((row) => <option key={row.id} value={row.id}>{row.name || t("Untitled dataset")} · {row.id.slice(0, 8)}</option>)}</select></label>
    <button className="button secondary" disabled={!key} onClick={() => void action("load")}>{t("Replace current draft with selected version")}</button>
    <label>{t("Restore draft JSON (replaces current draft)")}<input type="file" accept=".json" onChange={(e) => { void upload(e.target.files?.[0]); e.target.value = ""; }} /></label>
    <label>{t("Copy an existing custom dataset into a draft")}<select value={dataset} onChange={(e) => setDataset(e.target.value)}><option value="">{t("Choose a dataset")}</option>{datasets.map((d) => <option key={d.id} value={d.id}>{d.name} · {d.id.slice(0, 8)}</option>)}</select></label>
    <button className="button secondary" disabled={!dataset} onClick={() => void action("copy")}>{t("Replace draft with an editable dataset copy")}</button>
    {changes && <p>{t("Changes since loaded version: {added} added, {removed} removed, {changed} edited tasks.", { added: changes.added, removed: changes.removed, changed: changes.changed })} {changes.defaultsChanged && t("Shared defaults or dataset name changed.")}</p>}
    {message && <p role="status">{message}</p>}
    {error && <FormError>{error}</FormError>}
  </fieldset>{pending && <ConfirmDialog title={t("Replace the current draft?")} description={t("This will replace the name, shared environment and all tasks in your current draft. Saved versions and registered datasets will not be changed.")} confirmLabel={t("Replace draft")} cancelLabel={t("Keep current draft")} onCancel={() => setPending(undefined)} onConfirm={() => apply(pending)} />}</details>;
}
