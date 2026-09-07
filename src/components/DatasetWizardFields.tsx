import { useI18n } from "../i18n";
import { testTemplates, type EnvironmentDraft, type TaskDraft } from "../lib/dataset-authoring";

export function TaskFields({ task, defaults, onChange, onUpload }: {
  task: TaskDraft; defaults: EnvironmentDraft; onChange: (changes: Partial<TaskDraft>) => void;
  onUpload: (file: File | undefined, field: "hiddenPatch" | "goldPatch") => void;
}) {
  const { t } = useI18n();
  return <>
    <label>{t("Task ID")}<input value={task.id} placeholder="task-1" onChange={(e) => onChange({ id: e.target.value })} /></label>
    <label>{t("Task prompt · agent-visible")}<textarea rows={6} value={task.prompt} placeholder={t("Example: Fix normalize_name so leading and trailing whitespace is removed. Preserve internal spaces and handle empty input. Describe requirements, not the answer.")} onChange={(e) => onChange({ prompt: e.target.value })} /></label>
    <label className="check-line"><input type="checkbox" checked={!!task.override} onChange={(e) => onChange({ override: e.target.checked ? { ...defaults } : null })} />{t("Override repository and test environment for this task")}</label>
    {task.override ? <EnvironmentFields value={task.override} onChange={(override) => onChange({ override })} /> : <p className="wizard-inherited">{t("Using shared defaults")} · {defaults.repository} · <code>{defaults.baseCommit.slice(0, 12)}</code></p>}
    <fieldset><legend>{t("Pass/fail tests · evaluator-only")}</legend>
      <p>{t("Tests run at /workspace in an isolated container with no network. Exit code 0 means PASS; any nonzero exit means FAIL. Preinstall all dependencies in the test image.")}</p>
      <div className="form-grid two"><label>{t("Command format")}<select value={task.commandMode} onChange={(e) => {
        const mode = e.target.value as TaskDraft["commandMode"];
        if (mode === "argv") onChange({ commandMode: mode, command: JSON.stringify(["/bin/sh", "-eu", "-c", task.command]) });
        else {
          // Recover shell text if possible; preserve other argv commands via POSIX quoting.
          try {
            const argv: unknown = JSON.parse(task.command);
            const command = Array.isArray(argv) && argv.every((v) => typeof v === "string") ?
              argv.length === 4 && argv[0] === "/bin/sh" && argv[1] === "-eu" && argv[2] === "-c" ? argv[3] :
                argv.map((arg: string) => "'" + arg.replaceAll("'", "'\"'\"'") + "'").join(" ") : task.command;
            onChange({ commandMode: mode, command });
          } catch { onChange({ commandMode: mode }); }
        }
      }}><option value="shell">{t("Shell script (/bin/sh)")}</option><option value="argv">{t("Argument array (JSON)")}</option></select></label>
      <label>{t("Test command template")}<select value="" onChange={(e) => { const template = testTemplates[e.target.value as keyof typeof testTemplates]; if (template) onChange({ commandMode: "shell", command: template }); }}>
        <option value="">{t("Select to replace the command")}</option><option value="pytest">Python · pytest</option><option value="unittest">Python · unittest</option><option value="npm">Node.js · npm test</option>
      </select></label></div>
      <label>{t("Test command")}<textarea rows={4} spellCheck={false} value={task.command} placeholder={task.commandMode === "shell" ? "python -m pytest -q tests" : '["python", "-m", "pytest", "-q", "tests"]'} onChange={(e) => onChange({ command: e.target.value })} /></label>
      <p>{t("Templates only fill the command; they do not create assertions or install dependencies. Use argv for images without /bin/sh. Never hide failures with exit 0 or || true.")}</p>
      <details><summary>{t("How to add private test cases")}</summary><p>{t("Option A: run tests already present at the baseline (the agent can see those files). Option B: write private regression tests against that baseline and upload a git diff below; only the evaluator receives that patch.")}</p><p>{t("Example: assert normalize_name('  Ada  ') == 'Ada', assert normalize_name('') == '', and assert normalize_name('Ada Lovelace') == 'Ada Lovelace'. Replace these examples with assertions for your repository.")}</p>
        <p>{t("In a separate authoring checkout, add your new tests with intent-to-add so git diff includes them. Replace BASE with the pinned commit and the paths with your test files. Do not commit these hidden tests to the baseline.")}</p>
        <pre>{"git add -N tests/test_regression.py\ngit diff --binary BASE -- tests/test_regression.py > hidden-tests.patch"}</pre>
        <p>{t("Upload hidden-tests.patch below. The test command must collect these tests. Inspect the patch to ensure it contains assertions only, not the solution or credentials.")}</p>
      </details>
      <details><summary>{t("Hidden tests and reference fix (optional)")}</summary>
        <p className="wizard-notice">{t("These patches are evaluator-only, not context files. Keep them out of AGENTS.md, the repository baseline and agent prompts. Upload git diff text, not a list of test names.")}</p>
        <label>{t("Hidden test patch")}<textarea rows={5} spellCheck={false} value={task.hiddenPatch} onChange={(e) => onChange({ hiddenPatch: e.target.value })} /></label>
        <label>{t("Upload hidden test patch")}<input type="file" accept=".patch,.diff,.txt" onChange={(e) => { onUpload(e.target.files?.[0], "hiddenPatch"); e.target.value = ""; }} /></label>
        <label>{t("Reference fix patch")}<textarea rows={5} spellCheck={false} value={task.goldPatch} onChange={(e) => onChange({ goldPatch: e.target.value })} /></label>
        <label>{t("Upload reference fix patch")}<input type="file" accept=".patch,.diff,.txt" onChange={(e) => { onUpload(e.target.files?.[0], "goldPatch"); e.target.value = ""; }} /></label>
        <p>{t("The reference fix is stored as evaluator material. This wizard does not execute or verify it.")}</p>
      </details>
    </fieldset>
  </>;
}

export function EnvironmentFields({ value, onChange }: { value: EnvironmentDraft; onChange: (value: EnvironmentDraft) => void }) {
  const { t } = useI18n();
  const change = (patch: Partial<EnvironmentDraft>) => onChange({ ...value, ...patch });
  return <div className="wizard-environment">
    <label>{t("Repository URL / worker path")}<input value={value.repository} placeholder="https://git.company.example/team/repository.git" onChange={(e) => change({ repository: e.target.value })} /></label>
    <p>{t("GitHub is not required. Use Gitee or an internal Git URL reachable by the worker, without credentials. Local paths must be Linux paths visible inside the worker, not Windows paths.")}</p>
    <label>{t("Baseline commit (40 characters)")}<input value={value.baseCommit} placeholder="0123456789abcdef0123456789abcdef01234567" spellCheck={false} onChange={(e) => change({ baseCommit: e.target.value })} /></label>
    <p>{t("Run git rev-parse HEAD in the intended baseline checkout. Do not use the fixed commit or a moving branch.")}</p>
    <label>{t("Test environment")}<select value={value.mode} onChange={(e) => change({ mode: e.target.value as EnvironmentDraft["mode"] })}><option value="image">{t("Existing Docker image")}</option><option value="build">{t("Build from baseline Dockerfile")}</option></select></label>
    {value.mode === "image" ? <label>{t("Test image (not the Agent image)")}<input value={value.image} placeholder="registry.company.example/bench/project-tests:baseline" onChange={(e) => change({ image: e.target.value })} /></label> : <>
      <div className="form-grid two"><label>{t("Build context (relative to repository)")}<input value={value.context} onChange={(e) => change({ context: e.target.value })} /></label><label>{t("Dockerfile (relative to build context)")}<input value={value.dockerfile} onChange={(e) => change({ dockerfile: e.target.value })} /></label></div>
      <label>{t("Build arguments (JSON, no secrets)")}<textarea rows={2} value={value.buildArgs} spellCheck={false} onChange={(e) => change({ buildArgs: e.target.value })} /></label>
    </>}
    <p className="wizard-notice">{t("This image grades the submitted code; choose the coding Agent image later in the experiment. Include the language runtime and test dependencies, but never answers or private tests in the baseline build context.")}</p>
  </div>;
}
