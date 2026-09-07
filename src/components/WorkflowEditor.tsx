import type { AgentWorkflow } from "../domain/types";
import { useI18n } from "../i18n";
import { moveWorkflowStep, workflowError } from "../lib/workflow";

export function WorkflowEditor({ title, value, onChange, defaultPrompt }: {
  title: string; value: AgentWorkflow; onChange: (value: AgentWorkflow) => void; defaultPrompt?: string;
}) {
  const { t } = useI18n();
  const error = workflowError(value);
  const updateStep = (index: number, changes: Partial<AgentWorkflow["steps"][number]>) =>
    onChange({ ...value, steps: value.steps.map((step, i) => i === index ? { ...step, ...changes } : step) });
  return <details className="workflow-editor">
    <summary>{title} · {t("{count} prompt steps", { count: value.steps.length })}</summary>
    <p>{t("Startup commands run once inside each agent container before model calls. Steps run in order with fresh sessions and shared files. The workflow shares one token and time budget; failure stops later steps.")}</p>
    <fieldset><legend>{t("Startup commands")}</legend>
      <p>{t("Commands share one Bash shell, including exported variables and virtual-environment activation. Run as the unprivileged agent user; install system packages in the Dockerfile. Keep the checkout unchanged and pin dependency versions.")}</p>
      {value.setupCommands.map((command, index) => <div className="workflow-command" key={index}>
        <label>{t("Command {index}", { index: index + 1 })}<textarea rows={3} value={command} spellCheck={false}
          placeholder={'python3 -m venv "$HOME/bench-env"\nsource "$HOME/bench-env/bin/activate"\npython -m pip install -r requirements.txt'}
          onChange={(event) => onChange({ ...value, setupCommands: value.setupCommands.map((item, i) => i === index ? event.target.value : item) })} /></label>
        <button type="button" className="button tertiary" onClick={() => onChange({ ...value, setupCommands: value.setupCommands.filter((_, i) => i !== index) })}>{t("Remove command")}</button>
      </div>)}
      <button type="button" className="button secondary" disabled={value.setupCommands.length >= 20} onClick={() => onChange({ ...value, setupCommands: [...value.setupCommands, ""] })}>{t("Add command")}</button>
      <small>{t("Commands obey the selected container network policy. API-only does not automatically allow package registries. Never paste credentials here; reference saved environment variables.")}</small>
    </fieldset>
    {value.steps.map((step, index) => <fieldset key={index}>
      <legend>{t("Step {index}", { index: index + 1 })}</legend>
      <label>{t("Step name (optional)")}<input value={step.name} maxLength={120} onChange={(event) => updateStep(index, { name: event.target.value })} /></label>
      <label className="check-line"><input type="checkbox" checked={step.prompt === null}
        onChange={(event) => updateStep(index, { prompt: event.target.checked ? null : "{{default_prompt}}" })} />{t("Use default prompt")}</label>
      <label>{t(step.prompt === null ? "Default prompt preview" : "Step prompt")}
        <textarea rows={5} value={step.prompt ?? defaultPrompt ?? t("The worker resolves the default prompt for the selected task at execution time.")}
          readOnly={step.prompt === null} spellCheck={false} onChange={(event) => updateStep(index, { prompt: event.target.value })} />
      </label>
      <small>{t("Use {{default_prompt}} to include the existing generation instruction or the current task prompt. No conversation history is passed between steps; only repository files are shared.")}</small>
      <div className="toolbar">
        <button type="button" className="button tertiary" disabled={index === 0} onClick={() => onChange(moveWorkflowStep(value, index, -1))}>{t("Move up")}</button>
        <button type="button" className="button tertiary" disabled={index === value.steps.length - 1} onClick={() => onChange(moveWorkflowStep(value, index, 1))}>{t("Move down")}</button>
        <button type="button" className="button tertiary" disabled={value.steps.length === 1} onClick={() => onChange({ ...value, steps: value.steps.filter((_, i) => i !== index) })}>{t("Remove step")}</button>
      </div>
    </fieldset>)}
    <button type="button" className="button secondary" disabled={value.steps.length >= 50} onClick={() => onChange({ ...value, steps: [...value.steps, { name: "", prompt: "" }] })}>{t("Add prompt step")}</button>
    <p>{t("Both comparison arms use the same solver workflow. Startup commands never run in the hidden-test grader. A failed or interrupted workflow retries from a clean container, not from a partially completed step.")}</p>
    {error && <p className="form-error" role="alert">{t(error)}</p>}
  </details>;
}
