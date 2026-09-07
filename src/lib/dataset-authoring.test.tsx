import { describe, expect, it } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { commandArguments, datasetRows, draftIssues, duplicateTask, environmentErrors, newDatasetDraft, newTask } from "./dataset-authoring";
import { DatasetWizard } from "../components/DatasetWizard";
import { EnvironmentFields, TaskFields } from "../components/DatasetWizardFields";
import { I18nContext } from "../i18n.context";
import { translate } from "../i18n";
import { datasetWizardChinese } from "../i18n.dataset-wizard";

function validDraft() {
  const draft = newDatasetDraft();
  draft.name = "Regression suite";
  Object.assign(draft.defaults, { repository: "https://gitee.com/example/repository.git", baseCommit: "a".repeat(40), image: "registry.example/tests:baseline" });
  Object.assign(draft.tasks[0], { prompt: "  Fix the specified behavior.\n", command: "python -m pytest -q tests" });
  return draft;
}
describe("dataset authoring", () => {
  it("starts with one incomplete task and blocks unfilled steps", () => {
    const draft = newDatasetDraft();
    expect(draft.tasks).toHaveLength(1);
    expect(new Set(draftIssues(draft).map((issue) => issue.step))).toEqual(new Set([0, 1, 2]));
    expect(() => datasetRows(draft)).toThrow();
  });
  it("exports the existing custom manifest format, preserving prompts and evaluator patches exactly", () => {
    const draft = validDraft();
    draft.tasks[0].hiddenPatch = "diff --git a/tests/new.py b/tests/new.py\n";
    draft.tasks[0].goldPatch = "diff --git a/code.py b/code.py\n";
    const [row] = datasetRows(draft);
    expect(row.prompt).toBe(draft.tasks[0].prompt);
    expect(row.test.hiddenPatch).toBe(draft.tasks[0].hiddenPatch);
    expect(row.goldPatch).toBe(draft.tasks[0].goldPatch);
    expect(Object.keys(row).sort()).toEqual(["baseCommit", "goldPatch", "id", "image", "prompt", "repository", "test"]);
    expect(JSON.stringify(row.prompt)).not.toContain("diff --git");
  });
  it("inherits defaults live while preserving independent task overrides", () => {
    const draft = validDraft();
    draft.tasks = duplicateTask(draft.tasks, 0);
    draft.tasks[1].override = { ...draft.defaults, mode: "build", dockerfile: "Dockerfile.test", buildArgs: '{"PYTHON_VERSION":"3.12"}' };
    draft.defaults.baseCommit = "b".repeat(40);
    const rows = datasetRows(draft);
    expect(rows[0].baseCommit).toBe("b".repeat(40));
    expect(rows[1].baseCommit).toBe("a".repeat(40));
    expect(rows[1].image).toBeUndefined();
    expect(rows[1].build).toEqual({ dockerfile: "Dockerfile.test", context: ".", args: { PYTHON_VERSION: "3.12" } });
  });
  it("adds and duplicates with unique IDs and no shared environment object", () => {
    const draft = validDraft();
    draft.tasks[0].override = { ...draft.defaults };
    const tasks = duplicateTask(draft.tasks, 0);
    tasks[1].override!.image = "different:test";
    expect(tasks[0].override!.image).toBe(draft.defaults.image);
    expect(newTask([tasks[1]]).id).not.toBe(tasks[1].id);
    expect(tasks[0].prompt).toBe(tasks[1].prompt);
  });
  it("points duplicate IDs and invalid prompts to their tasks", () => {
    const draft = validDraft();
    draft.tasks.push({ ...draft.tasks[0], id: ` ${draft.tasks[0].id} `, prompt: " " });
    const issues = draftIssues(draft);
    expect(issues.filter((issue) => issue.message.includes("unique"))).toHaveLength(2);
    expect(issues.find((issue) => issue.message.includes("behavior"))?.task).toBe(1);
  });
  it("does not split quoted shell commands, interpolations or empty argv arguments", () => {
    const task = newTask();
    task.command = "printf '%s' 'a b'\npython -m pytest -k 'name or empty'";
    expect(commandArguments(task)).toEqual(["/bin/sh", "-eu", "-c", task.command]);
    task.commandMode = "argv";
    task.command = JSON.stringify(["python", "-c", 'print("two words")', ""]);
    expect(commandArguments(task)).toEqual(["python", "-c", 'print("two words")', ""]);
    for (const invalid of ["[]", "{}", '[" "]', '["pytest",1]', "pytest -q"]) {
      expect(() => commandArguments({ ...task, command: invalid })).toThrow();
    }
  });
  it("rejects unsafe build paths, malformed args and moving commits", () => {
    const draft = validDraft();
    for (const baseCommit of ["main", "a123", "z".repeat(40)]) expect(environmentErrors({ ...draft.defaults, baseCommit }).length).toBeGreaterThan(0);
    for (const dockerfile of ["/Dockerfile", "../Dockerfile", "C:\\Dockerfile", ".", ".GIT/config"]) {
      expect(environmentErrors({ ...draft.defaults, mode: "build", dockerfile }).length).toBeGreaterThan(0);
    }
    for (const buildArgs of ["[]", "null", '{"X":1}']) expect(environmentErrors({ ...draft.defaults, mode: "build", buildArgs }).length).toBeGreaterThan(0);
  });
  it("supports non-GitHub repositories and rejects embedded credentials/Windows paths", () => {
    const env = validDraft().defaults;
    for (const repository of ["https://git.company.example/group/repo.git", "/var/lib/ctxbench/sources/example", "ssh://git.company.example/group/repo.git"]) expect(environmentErrors({ ...env, repository })).toEqual([]);
    for (const repository of ["https://user:password@git.example/repo.git", "https://git.example/repo?token=secret", "C:\\repo", "repo", "http://git.example/repo"]) expect(environmentErrors({ ...env, repository }).length).toBeGreaterThan(0);
  });
  it("rejects NUL characters and invalid array members", () => {
    const draft = validDraft();
    draft.tasks[0].hiddenPatch = "bad\0patch";
    expect(draftIssues(draft).length).toBeGreaterThan(0);
    expect(() => datasetRows(draft)).toThrow();
  });
  it("renders a guided entry and all form sections in both languages", () => {
    const draft = validDraft();
    for (const locale of ["en", "zh-CN"] as const) {
      const render = (children: React.ReactNode) => renderToStaticMarkup(createElement(I18nContext.Provider, { value: { locale, t: (key, args) => translate(locale, key, args), setLocale: () => {} }, children }));
      expect(render(createElement(DatasetWizard, { onClose: () => {}, onComplete: () => {} }))).toContain(translate(locale, "Create custom dataset"));
      expect(render(createElement(EnvironmentFields, { value: draft.defaults, onChange: () => {} }))).toContain(translate(locale, "Test image (not the Agent image)"));
      const html = render(createElement(TaskFields, { task: draft.tasks[0], defaults: draft.defaults, onChange: () => {}, onUpload: () => {} }));
      expect(html).toContain(translate(locale, "Hidden test patch"));
      expect(html).toContain(translate(locale, "Task prompt · agent-visible"));
    }
    for (const [key, value] of Object.entries(datasetWizardChinese)) expect(translate("zh-CN", key)).toBe(value);
  });
});
