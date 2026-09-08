import { useRef, useState } from "react";
import type { DatasetRecord } from "../domain/types";
import { useI18n } from "../i18n";
import { saveText, workerRequest } from "../lib/desktop";
import { authoringSteps, datasetRows, draftIssues, duplicateTask, newDatasetDraft, newTask,
  type DatasetDraft, type TaskDraft } from "../lib/dataset-authoring";
import { Modal } from "./WorkbenchDialogs";
import { ConfirmDialog, FormError } from "./Dialogs";
import { EnvironmentFields, TaskFields } from "./DatasetWizardFields";
import { DatasetSelfTest } from "./DatasetSelfTest";
import { DatasetDrafts } from "./DatasetDrafts";

export function DatasetWizard({ onClose, onComplete }: { onClose: () => void; onComplete: (dataset: DatasetRecord) => void }) {
  const { t } = useI18n();
  const [draft, setDraft] = useState(newDatasetDraft);
  const [step, setStep] = useState(0);
  const [selected, setSelected] = useState(0);
  const [showIssues, setShowIssues] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [validated, setValidated] = useState("");
  const [created, setCreated] = useState<DatasetRecord>();
  const [discard, setDiscard] = useState(false);
  const [remove, setRemove] = useState<number>();
  const heading = useRef<HTMLHeadingElement>(null);
  const validation = useRef<HTMLDivElement>(null);
  const issues = draftIssues(draft);
  const payload = issues.length ? "" : JSON.stringify({ name: draft.name.trim(), benchmark: "custom", rows: datasetRows(draft) });
  const update = (next: DatasetDraft) => { setDraft(next); setValidated(""); setError(""); };
  const updateTask = (changes: Partial<TaskDraft>) => update({ ...draft, tasks: draft.tasks.map((item, index) => index === selected ? { ...item, ...changes } : item) });
  const go = (next: number) => { setStep(next); setShowIssues(false); setError(""); setTimeout(() => heading.current?.focus(), 0); };
  const revealIssues = () => { setShowIssues(true); window.setTimeout(() => validation.current?.focus(), 0); };
  const next = () => { if (issues.some((issue) => issue.step <= step)) revealIssues(); else go(step + 1); };
  const close = () => { if (busy) return; if (created || JSON.stringify(draft) === JSON.stringify(newDatasetDraft())) onClose(); else setDiscard(true); };
  const execute = async (action: "validate" | "export" | "create") => {
    if (busy) return;
    if (!payload) { revealIssues(); return; }
    setBusy(true); setError(""); setValidated("");
    try {
      const body = JSON.parse(payload);
      if (action === "create") {
        const result = await workerRequest<DatasetRecord>("/datasets", "POST", body);
        setCreated(result); onComplete(result);
      } else {
        await workerRequest("/datasets/validate", "POST", body);
        setValidated(payload);
        if (action === "export") await saveText("custom-dataset.json", JSON.stringify(body.rows, null, 2));
      }
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { setBusy(false); }
  };
  const uploadPatch = async (file: File | undefined, field: "hiddenPatch" | "goldPatch") => {
    if (!file || busy) return;
    if (file.size > 2_000_000) { setError("Patch files are limited to 2 MB."); return; }
    // Lock selection while reading, so a slow read cannot attach tests to another task.
    setBusy(true); setError("");
    try { updateTask({ [field]: await file.text() }); }
    catch { setError("Could not read the patch file."); }
    finally { setBusy(false); }
  };
  return <Modal title={t("Create custom dataset")} busy={busy} onClose={close}>
    <div className="dataset-wizard" aria-busy={busy}>
      {discard && !created && <ConfirmDialog title={t("Discard unsaved changes?")} description={t("Closing discards the current draft edits. Saved draft versions and exported files are kept; no dataset has been created yet.")} cancelLabel={t("Keep editing")} confirmLabel={t("Discard and close")} onCancel={() => setDiscard(false)} onConfirm={onClose} />}
      {remove !== undefined && <ConfirmDialog title={t("Remove this task")} description={`${draft.tasks[remove].id} — ${t("Removing a task discards its prompt and test definition from this draft.")}`} confirmLabel={t("Confirm remove task")} onCancel={() => setRemove(undefined)} onConfirm={() => { update({ ...draft, tasks: draft.tasks.filter((_, index) => index !== remove) }); setSelected(Math.max(0, remove - 1)); setRemove(undefined); }} />}
      {created ? <section className="wizard-success" role="status">
        <h3>{t("Dataset created")}</h3><p>{created.name} · {t(created.count === 1 ? "1 task" : "{count} tasks", { count: created.count })}</p>
        <p>{t("Open New experiment and select this dataset. Model, context arms, workflows and repeats are configured there.")}</p>
        <p>{t("The definition is frozen by hash. Registration itself does not execute tests or call an Agent; any self-test is a separate operation.")}</p>
        <button className="button primary" onClick={onClose}>{t("Done")}</button>
      </section> : <>
        <DatasetDrafts draft={draft} disabled={busy} onBusy={setBusy} onLoad={(value) => { update(value); setSelected(0); go(0); }} />
        <ol className="wizard-steps" aria-label={t("Dataset creation steps")}>
          {authoringSteps.map((label, index) => <li key={label} aria-current={index === step ? "step" : undefined}>
            <button disabled={busy || index > step} onClick={() => go(index)}><span>{index + 1}</span>{t(label)}</button>
          </li>)}
        </ol>
        <h3 ref={heading} tabIndex={-1}>{t(authoringSteps[step])}</h3>
        <fieldset className="wizard-fields" disabled={busy}>
          {step === 0 && <>
            <p className="wizard-lead">{t("Build a reusable task set without writing JSON. Each task pairs a coding request with an executable test command.")}</p>
            <label>{t("Dataset name")}<input autoFocus value={draft.name} placeholder={t("Example: Team service regression suite")} onChange={(e) => update({ ...draft, name: e.target.value })} /></label>
            <div className="wizard-guide"><h4>{t("Design a useful benchmark")}</h4><ol>
              <li>{t("Choose a baseline before the fix. Describe observable behavior, inputs, outputs and edge cases in the task prompt.")}</li>
              <li>{t("Write deterministic assertions: the buggy baseline should fail, and a correct fix should pass. A test command is not a coding prompt.")}</li>
              <li>{t("One task is one independent coding problem. Multiple assertions belong in its tests; repeated runs are configured later in an experiment.")}</li>
            </ol></div>
            <p>{t("Keep answers, target PRs, hidden tests and mined constraints out of the task prompt and baseline. Context packages are generated or imported separately from that same baseline.")}</p>
          </>}
          {step === 1 && <>
            <p>{t("Tasks inherit these defaults live. A task can opt into its own repository, commit and test environment in the next step.")}</p>
            <EnvironmentFields value={draft.defaults} onChange={(defaults) => update({ ...draft, defaults })} />
          </>}
          {step === 2 && <>
            <div className="wizard-actions">
              <label className="wizard-task-picker">{t("Editing task")}<select value={selected} onChange={(e) => { setSelected(Number(e.target.value)); setError(""); }}>
                {draft.tasks.map((item, index) => <option key={index} value={index}>{index + 1}. {item.id || t("Untitled task")}{issues.some((issue) => issue.task === index) ? ` · ${t("Incomplete")}` : ""}</option>)}
              </select></label>
              <button className="button secondary" disabled={draft.tasks.length >= 10_000} onClick={() => { update({ ...draft, tasks: [...draft.tasks, newTask(draft.tasks)] }); setSelected(draft.tasks.length); }}>{t("Add task")}</button>
              <button className="button secondary" disabled={draft.tasks.length >= 10_000} onClick={() => { update({ ...draft, tasks: duplicateTask(draft.tasks, selected) }); setSelected(draft.tasks.length); }}>{t("Duplicate task")}</button>
            </div>
            <TaskFields task={draft.tasks[selected]} defaults={draft.defaults} onChange={updateTask} onUpload={(file, field) => void uploadPatch(file, field)} />
            <button className="button secondary" disabled={draft.tasks.length === 1} onClick={() => setRemove(selected)}>{t("Remove this task")}</button>
          </>}
          {step === 3 && <>
            <p className="wizard-lead">{draft.name} · {t(draft.tasks.length === 1 ? "1 task" : "{count} tasks", { count: draft.tasks.length })} · {t("Custom")}</p>
            <div className="table-scroll"><table className="wizard-review"><thead><tr>{["Task ID", "Baseline / test image", "Private tests"].map((key) => <th key={key}>{t(key)}</th>)}</tr></thead><tbody>{draft.tasks.map((item, index) => {
              const env = item.override ?? draft.defaults;
              return <tr key={index}><td><button className="text-button" onClick={() => { setSelected(index); go(2); }}>{item.id}</button></td><td><div>{env.repository}</div><code>{env.baseCommit.slice(0, 12)}</code><div>{env.mode === "image" ? env.image : `${env.context}/${env.dockerfile}`}</div></td><td>{t(item.hiddenPatch.trim() ? "Hidden patch" : "Command only")}</td></tr>;
            })}</tbody></table></div>
            <p className="wizard-notice">{t("Validation checks only the definition: required fields, unique IDs, pinned commits and environment format. It does not clone repositories, pull images, apply patches or run tests. Verify baseline FAIL / correct-fix PASS before trusting scores.")}</p>
            <p>{t("Do not include credentials in prompts, patches, image URLs or build arguments. This dataset is frozen on creation and can be reused by multiple experiments.")}</p>
            <DatasetSelfTest payload={payload} disabled={busy} />
            <details><summary>{t("Preview export JSON · contains evaluator-only material")}</summary><pre>{payload ? JSON.stringify(JSON.parse(payload).rows, null, 2) : t("Fix the highlighted fields before continuing.")}</pre></details>
            <div className="wizard-actions"><button className="button secondary" onClick={() => void execute("validate")}>{t("Validate definition")}</button><button className="button secondary" onClick={() => void execute("export")}>{t("Export task JSON")}</button></div>
            {validated === payload && !!payload && <p className="wizard-valid" role="status">{t("Definition valid. Execution results, if requested, are shown separately in self-test.")}</p>}
          </>}
        </fieldset>
        {showIssues && issues.length > 0 && <div ref={validation} tabIndex={-1} className="form-error" role="alert"><p>{t("Fix the highlighted fields before continuing.")}</p><ul>{issues.filter((issue) => issue.step <= step).map((issue, index) => <li key={index}><button className="text-button" onClick={() => { go(issue.step); if (issue.task !== undefined) setSelected(issue.task); setShowIssues(true); }}>{issue.task !== undefined ? `${t("Task")} ${issue.task + 1}: ` : ""}{t(issue.message)}</button></li>)}</ul></div>}
        {error && <FormError>{t(error)}</FormError>}
        <footer className="wizard-footer"><button className="button secondary" disabled={busy} onClick={step ? () => go(step - 1) : close}>{t(step ? "Back" : "Cancel")}</button>
          <span aria-live="polite">{busy ? t("Working…") : t("Step {step} of 4", { step: step + 1 })}</span>
          {step < 3 ? <button className="button primary" disabled={busy} onClick={next}>{t("Next step")}</button> : <button className="button primary" disabled={busy || !!issues.length} onClick={() => void execute("create")}>{t("Create dataset")}</button>}
        </footer>
      </>}
    </div>
  </Modal>;
}
