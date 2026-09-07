import { useId } from "react";
import { useI18n } from "../i18n";
import { agentArgsError, moveAgentArg } from "../lib/agent-args";

export function AgentArgsField({ value, onChange }: { value: string[]; onChange: (value: string[]) => void }) {
  const { t } = useI18n();
  const hintId = useId();
  const error = agentArgsError(value);
  return <fieldset className="agent-args-editor">
    <legend>{t("Agent startup arguments")}</legend>
    <p id={hintId}>{t("One argument per row, in order. Enter --tools and read,bash in two rows. Spaces stay inside a single argument; do not add shell quotes. Variables and shell expressions are not expanded.")}</p>
    {!value.length && <p>{t("No extra arguments; use the adapter defaults.")}</p>}
    {value.map((arg, index) => <div className="agent-arg-row" key={index}>
      <label>{t("Argument {index}", { index: index + 1 })}<input value={arg} spellCheck={false} autoComplete="off" aria-describedby={hintId}
        onChange={(event) => onChange(value.map((item, i) => i === index ? event.target.value : item))} /></label>
      <div className="toolbar">
        <button type="button" className="button tertiary" aria-label={t("Move argument {index} up", { index: index + 1 })} disabled={index === 0} onClick={() => onChange(moveAgentArg(value, index, -1))}>{t("Move up")}</button>
        <button type="button" className="button tertiary" aria-label={t("Move argument {index} down", { index: index + 1 })} disabled={index === value.length - 1} onClick={() => onChange(moveAgentArg(value, index, 1))}>{t("Move down")}</button>
        <button type="button" className="button tertiary" aria-label={t("Remove argument {index}", { index: index + 1 })} onClick={() => onChange(value.filter((_, i) => i !== index))}>{t("Remove argument")}</button>
      </div>
    </div>)}
    <button type="button" className="button secondary" disabled={value.length >= 128} onClick={() => onChange([...value, ""])}>{t("Add argument")}</button>
    <p>{t("Frozen for every agent stage, prompt step, comparison arm and repeat in this experiment; never passed to the hidden-test grader. Changing arguments creates a different generated-context cache key.")}</p>
    <small>{t("Built-in Pi supports --tools, --exclude-tools, --no-tools, --no-builtin-tools, --no-themes, --no-context-files and --verbose. Provider/model, prompts, sessions and RPC are benchmark-controlled. Custom images implement their own options and must support the startup-arguments protocol.")}</small>
    <p>{t("Arguments are saved in experiment records. Never paste keys here; use environment variables. This field does not run commands before startup.")}</p>
    {error && <p className="form-error" role="alert">{t(error)}</p>}
  </fieldset>;
}
