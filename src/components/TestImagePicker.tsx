import { useEffect, useState } from "react";
import { useI18n } from "../i18n";
import { listLocalImages } from "../lib/desktop";
import { savedDistribution } from "../lib/wsl";
import { bundledImageRole, imageRoleHints } from "../lib/test-images";

export function TestImagePicker({ value, onChange }: { value: string; onChange: (image: string) => void }) {
  const { t } = useI18n();
  const distribution = savedDistribution();
  const [images, setImages] = useState<string[]>([]); const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false); const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    let alive = true; setLoading(true); setError(false); setImages([]);
    if (!distribution) { setLoading(false); return; }
    void listLocalImages(distribution).then((result) => { if (alive) { setImages(result.error ? [] : result.images); setError(!!result.error); } })
      .catch(() => { if (alive) setError(true); }).finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [distribution, refresh]);
  const role = bundledImageRole(value.trim());
  return <section className="test-image-picker" aria-label={t("Choose the test runtime")}>
    <p>{t("A test image is the toolbox used to run your assertions after coding. It must contain the project's language runtime and test dependencies; importing the four application images does not install every project's dependencies.")}</p>
    <p>{t("New experiments prepare a clean Agent build environment from this project's dependencies by default. You do not need to install Pi into every test image. Knowledge generation and coding use the same frozen dependency environment; custom grading runs separately without model credentials.")}</p>
    <div className="test-image-selection"><label>{t("Choose an installed image")}<select disabled={loading || !images.length} value={images.includes(value) ? value : ""} onChange={(event) => { if (event.target.value) onChange(event.target.value); }}>
      <option value="">{t(loading ? "Listing local images…" : "Select an image, or enter one below")}</option>
      <optgroup label={t("Project / other images")}>{images.filter((image) => !bundledImageRole(image)).map((image) => <option key={image}>{image}</option>)}</optgroup>
      <optgroup label={t("Application images — read the role notes")}>{images.filter((image) => bundledImageRole(image)).map((image) => <option key={image}>{image}</option>)}</optgroup>
    </select></label><button type="button" className="button secondary" disabled={loading || !distribution} onClick={() => setRefresh((value) => value + 1)}>{t("Refresh local images")}</button></div>
    <p role="status">{t(!distribution ? "Select your WSL distribution in Settings → Runtime & diagnostics to list images. You can still enter a reference below." : error ? "Could not list images. Check WSL and Docker in Settings → Runtime & diagnostics, then refresh. Manual entry is still available." : loading ? "Listing local images…" : "Images listed from WSL: {distribution}. Listing checks presence only, not test compatibility.", { distribution })}</p>
    {!loading && !error && distribution && !images.length && <p>{t("No tagged local images found. Build or import the required images first, or enter a local image digest.")}</p>}
    <label>{t("Test image reference")}<input value={value} autoComplete="off" spellCheck={false} placeholder="ctxbench/agent-pi:0.1.0" onChange={(event) => onChange(event.target.value)} /></label>
    <p>{t("You may reuse a suitable image or type an internal registry tag/digest. An image not listed here may require a pull during preparation; in an offline network, import it into the selected Docker environment first.")}</p>
    {role && <p className="wizard-notice" role="status">{t(imageRoleHints[role])}</p>}
    <details><summary>{t("Can I use the four imported application images?")}</summary>
      <dl className="image-role-guide">{(["agent", "harness", "worker", "proxy"] as const).map((kind) => <div key={kind}><dt><code>{({ agent: "agent-pi", harness: "official-harness", worker: "worker", proxy: "egress-proxy" })[kind]}</code></dt><dd>{t(imageRoleHints[kind])}</dd></div>)}</dl>
      <p>{t("For custom tests, the evaluator overrides the image entrypoint and runs only your test command in /workspace. Reusing the Pi image does not launch Pi, call a model or pass Agent API keys.")}</p>
    </details>
    <details><summary>{t("How do I choose or prepare a suitable image?")}</summary><ol>
      <li>{t("Simple Python standard-library tests: select the imported Pi image and use python3 -m unittest discover -s tests -v. Node.js scripts with no extra dependencies can use node; npm test requires a test script in package.json.")}</li>
      <li>{t("For pytest, databases, compilers or project packages, prepare a project-specific image. Use Settings → Image adaptation, or choose Build from baseline Dockerfile above. Build/import dependencies before offline grading; do not install them during the test command.")}</li>
      <li>{t("Use an absolute location such as /opt/venv for installed dependencies. /workspace is replaced with a clean baseline plus the candidate patch, so dependencies baked only into /workspace are hidden during grading.")}</li>
      <li>{t("In Review and create, run the baseline / reference self-test. Baseline FAIL and reference PASS are required; missing commands or modules indicate an environment problem, not an Agent failure.")}</li>
    </ol></details>
  </section>;
}
