import { useEffect, useId, useState } from "react";
import type { RuntimeSettings } from "../domain/types";
import { useI18n } from "../i18n";
import { workerRequest } from "../lib/desktop";
import { environmentNamesError, parseEnvironmentNames } from "../lib/environment";

export function EnvironmentNamesField({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  const { t } = useI18n();
  const hintId = useId();
  const [credentials, setCredentials] = useState<RuntimeSettings["credentials"]>([]);
  useEffect(() => {
    let active = true;
    void workerRequest<RuntimeSettings>("/runtime").then((settings) => {
      if (active) setCredentials(settings.credentials.filter((item) => item.configured));
    }).catch(() => {});
    return () => { active = false; };
  }, []);
  const names = parseEnvironmentNames(value);
  const error = environmentNamesError(value);
  return <fieldset className="environment-names">
    <legend>{t("Environment variable names")}</legend>
    {credentials.length > 0 && <div className="environment-options">
      {credentials.map(({ name }) => <label className="check-line" key={name}>
        <input type="checkbox" checked={names.includes(name)} onChange={(event) => onChange(
          (event.target.checked ? [...new Set([...names, name])] : names.filter((item) => item !== name)).join("\n"),
        )} /><span>{name}</span>
      </label>)}
    </div>}
    <label>{t("Selected variable names")}
      <textarea rows={3} value={value} onChange={(event) => onChange(event.target.value)}
        spellCheck={false} autoComplete="off" aria-describedby={hintId} aria-invalid={!!error}
        placeholder={"OPENAI_API_KEY\nOPENAI_BASE_URL"} />
    </label>
    <small id={hintId}>{t("Select multiple configured variables, or enter names separated by newlines, spaces or commas. Save their values in Infrastructure first.")}</small>
    {error && <p className="form-error" role="alert">{t(error)}</p>}
  </fieldset>;
}
