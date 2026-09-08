import { useI18n, type Translate } from "../i18n";
import { workerRequest } from "../lib/desktop";
import type { RuntimeSettings } from "../domain/types";

export async function requireProjectEnvironment(enabled: boolean, t: Translate) {
  if (!enabled) return;
  const settings = await workerRequest<RuntimeSettings>("/runtime");
  if (settings.projectEnvironmentVersion !== 1) throw new Error(t("Project build environments require the matching new local service image. Update Settings → Application images and restart the service before creating this plan."));
}

export function ProjectEnvironmentField({ value, onChange }: { value: boolean; onChange: (value: boolean) => void }) {
  const { t } = useI18n();
  return <fieldset><legend>{t("Agent build environment")}</legend>
    <label className="check-line"><input type="checkbox" checked={value} onChange={(event) => onChange(event.target.checked)} />{t("Prepare project dependencies for knowledge generation and coding (recommended)")}</label>
    <p>{t("Before any model call, prepare a clean project environment with Pi, compilers and the dependencies supplied by the dataset. The Agent can build code and run visible tests. Both context arms reuse the same frozen environment; hidden tests remain in separate grading containers.")}</p>
    <details><summary>{t("Preparation, caching and offline use")}</summary><p>{t("Official tasks use their project images and setup recipes. Custom tasks use the test image or baseline Dockerfile you selected; missing dependencies are not guessed or installed automatically. In an offline network, import the project and Pi images first.")}</p>
    <p>{t("First preparation may take several minutes and extra disk space. A matching repository, baseline, dependency image and Pi adapter reuses the cache. Environment progress appears in the task or experiment list; no model tokens are used for preparation.")}</p></details>
    {!value && <p className="wizard-notice">{t("Advanced as-is mode: the selected Agent image must already contain your build dependencies. Nothing is added automatically. Use this for company Agents with their own prepared adapter; old experiments retain their original mode.")}</p>}
  </fieldset>;
}
