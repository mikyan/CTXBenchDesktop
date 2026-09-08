import { z } from "zod";

// Drafts are deliberately distinct from the evaluator manifest. Export is explicit;
// neither prompts nor hidden tests are persisted to browser storage.
const text = z.string().max(2_000_000).refine((value) => !value.includes("\0"));
const environmentSchema = z.object({
  repository: text, baseCommit: text, mode: z.enum(["image", "build"]),
  image: text, dockerfile: text, context: text, buildArgs: text,
}).strict();
const taskSchema = z.object({
  id: text, prompt: text, override: environmentSchema.nullable(),
  commandMode: z.enum(["shell", "argv"]), command: text, hiddenPatch: text, goldPatch: text,
  metadata: z.record(z.string(), z.unknown()).optional(),
}).strict();
export const draftSchema = z.object({
  format: z.literal("ctxbench-dataset-draft"), version: z.literal(1), name: text,
  defaults: environmentSchema, tasks: z.array(taskSchema).min(1).max(10_000),
}).strict();
export type DatasetDraft = z.infer<typeof draftSchema>;
export type TaskDraft = z.infer<typeof taskSchema>;
export type EnvironmentDraft = z.infer<typeof environmentSchema>;
export interface CustomTaskManifest {
  id: string; repository: string; baseCommit: string; prompt: string;
  image?: string; build?: { dockerfile: string; context: string; args: Record<string, string> };
  test: { command: string[]; hiddenPatch?: string }; goldPatch?: string;
  metadata?: Record<string, unknown>;
}
export interface DraftIssue { step: number; message: string; task?: number }
export function draftFromManifest(name: string, rows: CustomTaskManifest[]): DatasetDraft {
  if (!Array.isArray(rows) || !rows.length) throw Error("The dataset has no editable custom tasks.");
  if (rows.some((row) => row.image && row.build)) throw Error("This manifest uses both image and build. Choose one environment in JSON before copying it into the wizard.");
  const environment = (row: CustomTaskManifest): EnvironmentDraft => ({ repository: row.repository, baseCommit: row.baseCommit,
    mode: row.image ? "image" : "build", image: row.image ?? "", dockerfile: row.build?.dockerfile ?? "Dockerfile",
    context: row.build?.context ?? ".", buildArgs: JSON.stringify(row.build?.args ?? {}, null, 2) });
  return draftSchema.parse({ format: "ctxbench-dataset-draft", version: 1, name, defaults: environment(rows[0]),
    tasks: rows.map((row) => ({ id: row.id, prompt: row.prompt, override: environment(row), commandMode: "argv",
      command: JSON.stringify(row.test.command), hiddenPatch: row.test.hiddenPatch ?? "", goldPatch: row.goldPatch ?? "", ...(row.metadata ? { metadata: row.metadata } : {}) })) });
}
export function draftDifference(before: DatasetDraft, after: DatasetDraft) {
  const previous = new Map(before.tasks.map((task) => [task.id, task]));
  const current = new Map(after.tasks.map((task) => [task.id, task]));
  return { added: after.tasks.filter((task) => !previous.has(task.id)).length,
    removed: before.tasks.filter((task) => !current.has(task.id)).length,
    changed: after.tasks.filter((task) => previous.has(task.id) && JSON.stringify(previous.get(task.id)) !== JSON.stringify(task)).length,
    defaultsChanged: before.name !== after.name || JSON.stringify(before.defaults) !== JSON.stringify(after.defaults) };
}
export const authoringSteps = ["Dataset details", "Shared defaults", "Tasks and tests", "Review and create"];
export const testTemplates = {
  pytest: "python3 -m pytest -q tests",
  unittest: "python3 -m unittest discover -s tests -v",
  npm: "npm test",
};
export function newTask(tasks: TaskDraft[] = []): TaskDraft {
  let number = tasks.length + 1;
  while (tasks.some((task) => task.id === `task-${number}`)) number++;
  return { id: `task-${number}`, prompt: "", override: null, commandMode: "shell", command: "", hiddenPatch: "", goldPatch: "" };
}
export function newDatasetDraft(): DatasetDraft {
  return { format: "ctxbench-dataset-draft", version: 1, name: "",
    defaults: { repository: "", baseCommit: "", mode: "image", image: "", dockerfile: "Dockerfile", context: ".", buildArgs: "{}" },
    tasks: [newTask()] };
}
export function duplicateTask(tasks: TaskDraft[], index: number): TaskDraft[] {
  const source = tasks[index];
  if (!source) return tasks;
  return [...tasks, { ...source, override: source.override ? { ...source.override } : null, id: newTask(tasks).id }];
}
function relativePath(value: string, allowRoot = false): boolean {
  if (allowRoot && value === ".") return true;
  return !!value && value !== "." && !value.startsWith("/") && !value.includes("\\") && !value.includes(":") &&
    value.split("/").every((part) => part && !["..", ".git"].includes(part.toLowerCase()));
}
export function environmentErrors(env: EnvironmentDraft): string[] {
  const errors: string[] = [];
  const repo = env.repository.trim();
  let validRepo = repo.startsWith("/") && !repo.startsWith("//");
  try {
    const url = new URL(repo);
    validRepo = ["https:", "ssh:", "git:"].includes(url.protocol) && !!url.hostname && !url.username && !url.password && !url.search && !url.hash;
  } catch { /* A worker-local absolute Linux path does not have a URL scheme. */ }
  if (!validRepo) errors.push("Use a credential-free HTTPS/SSH/Git URL or an absolute Linux path on the worker.");
  if (!/^[0-9a-fA-F]{40}$/.test(env.baseCommit.trim())) errors.push("Pin a full 40-character baseline commit, not a branch or short hash.");
  if (env.mode === "image") {
    if (!env.image.trim() || /\s/.test(env.image.trim())) errors.push("Provide a test image reference without whitespace.");
  } else {
    if (!relativePath(env.dockerfile.trim()) || !relativePath(env.context.trim(), true)) errors.push("Build paths must stay inside the baseline repository; use Linux relative paths.");
    try {
      const args: unknown = JSON.parse(env.buildArgs);
      if (!args || typeof args !== "object" || Array.isArray(args) || !Object.values(args).every((v) => typeof v === "string")) throw Error();
    } catch { errors.push("Build arguments must be a JSON object with string values."); }
  }
  return errors;
}
export function commandArguments(task: TaskDraft): string[] {
  if (!task.command.trim()) throw Error("Provide a test command that exits nonzero when an assertion fails.");
  if (task.commandMode === "shell") return ["/bin/sh", "-eu", "-c", task.command];
  let command: unknown;
  try { command = JSON.parse(task.command); } catch { throw Error("Test arguments must be a nonempty JSON array of strings."); }
  if (!Array.isArray(command) || !command.length || !command.every((arg) => typeof arg === "string" && !arg.includes("\0")) || !command[0].trim())
    throw Error("Test arguments must be a nonempty JSON array of strings.");
  return command;
}
export function draftIssues(draft: DatasetDraft): DraftIssue[] {
  const issues: DraftIssue[] = [];
  if (!draft.name.trim()) issues.push({ step: 0, message: "Give the dataset a name." });
  for (const message of environmentErrors(draft.defaults)) issues.push({ step: 1, message });
  const ids = new Map<string, number>();
  for (const task of draft.tasks) ids.set(task.id.trim(), (ids.get(task.id.trim()) ?? 0) + 1);
  draft.tasks.forEach((task, index) => {
    const add = (message: string) => issues.push({ step: 2, task: index, message });
    if (!task.id.trim()) add("Give every task a unique ID.");
    else if (ids.get(task.id.trim())! > 1) add("Task IDs must be unique within this dataset.");
    if (!task.prompt.trim()) add("Describe the behavior the agent must implement.");
    if (task.override) environmentErrors(task.override).forEach(add);
    try { commandArguments(task); } catch (error) { add((error as Error).message); }
  });
  if (!draftSchema.safeParse(draft).success) issues.push({ step: 2, message: "Invalid draft: check task count, field sizes, and NUL characters." });
  return issues;
}
export function datasetRows(draft: DatasetDraft): CustomTaskManifest[] {
  if (draftIssues(draft).length) throw Error("Fix the highlighted fields before continuing.");
  return draft.tasks.map((task) => {
    const env = task.override ?? draft.defaults;
    return {
      id: task.id.trim(), repository: env.repository.trim(), baseCommit: env.baseCommit.trim(), prompt: task.prompt,
      ...(env.mode === "image" ? { image: env.image.trim() } : { build: {
        dockerfile: env.dockerfile.trim(), context: env.context.trim(), args: JSON.parse(env.buildArgs),
      } }),
      test: { command: commandArguments(task), ...(task.hiddenPatch.trim() ? { hiddenPatch: task.hiddenPatch } : {}) },
      ...(task.goldPatch.trim() ? { goldPatch: task.goldPatch } : {}),
      ...(task.metadata ? { metadata: task.metadata } : {}),
    };
  });
}
