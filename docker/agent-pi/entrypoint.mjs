import { createHash } from "node:crypto";
import { spawnSync } from "node:child_process";
import { appendFile, cp, lstat, mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { aggregateStats, runPiStep, runStartup } from "./workflow-runtime.mjs";
import { piAgentArgs, agentArgsReceipt } from "./agent-args.mjs";

const requestPath = "/ctxbench/request.json";
const outputRoot = "/ctxbench/output";
const workspace = "/workspace";

const request = JSON.parse(await readFile(requestPath, "utf8"));
if (request.schemaVersion !== 1 || !request.runId || !request.prompt || !request.model) {
  throw new Error("Invalid CTXBench agent request.");
}

await mkdir(outputRoot, { recursive: true });
const liveTrajectoryPath = path.join(outputRoot, "trajectory.live.jsonl");
await writeFile(liveTrajectoryPath, "", "utf8");
spawnSync("git", ["config", "--global", "--add", "safe.directory", workspace]);
const initialCommit = spawnSync("git", ["rev-parse", "HEAD"], { cwd: workspace, encoding: "utf8" }).stdout?.trim();
if (!/^[0-9a-f]{40}$/.test(initialCommit ?? "")) throw new Error("Workspace must have a frozen Git baseline.");

const secretValues = Object.entries(process.env)
  .filter(([name, value]) => value && ((request.envNames ?? []).includes(name) || /(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)/i.test(name)))
  .map(([, value]) => value)
  .sort((left, right) => right.length - left.length);

const redact = (value) => secretValues.reduce((text, secret) => text.replaceAll(secret, "[REDACTED]"), value);
const trajectory = [];
const capability = request.metadata?.capability ?? "tree-only";
const workflow = request.workflow ?? { version: 1, setupCommands: [], steps: [{ name: "", prompt: request.prompt }] };
if (workflow.version !== 1 || !Array.isArray(workflow.setupCommands) || !Array.isArray(workflow.steps) || !workflow.steps.length) {
  throw new Error("Invalid workflow protocol.");
}
const deadline = Date.now() + Math.max(1, request.timeoutSeconds ?? 2700) * 1000;
const steps = [];
let cumulativeTokens = 0, workflowError = null, liveWrites = Promise.resolve();
let argsReceipt = {};
try {
  const args = piAgentArgs(request.agentArgs);
  if (args.some((arg) => redact(arg) !== arg)) throw new Error("Use environment variables for credentials, not startup arguments.");
  request.agentArgs = Object.freeze(args);
  argsReceipt = agentArgsReceipt(args);
} catch (error) { workflowError = String(error.message); }
const persistWorkflow = () => writeFile(path.join(outputRoot, "workflow.json"), redact(JSON.stringify({
  version: 1, setup: { ...setup, env: undefined, log: undefined }, steps,
  plannedSteps: workflow.steps.length, cumulativeTokens, error: workflowError,
}, null, 2)), "utf8");
const setup = await runStartup(workflowError ? [] : workflow.setupCommands, { cwd: workspace, env: process.env, timeoutMs: deadline - Date.now(), redact });
await writeFile(path.join(outputRoot, "setup.log"), setup.log, "utf8");
if (!["skipped", "completed"].includes(setup.status)) workflowError = setup.error ?? "Startup commands timed out.";
if (!workflowError && workflow.setupCommands.length) {
  const current = spawnSync("git", ["rev-parse", "HEAD"], { cwd: workspace, encoding: "utf8" });
  const changed = spawnSync("git", ["status", "--porcelain", "--untracked-files=all"], { cwd: workspace, encoding: "utf8" });
  const ignored = spawnSync("git", ["ls-files", "--others", "--ignored", "--exclude-standard", "-z"], { cwd: workspace, encoding: "utf8" });
  if (current.status !== 0 || current.stdout.trim() !== initialCommit || changed.status !== 0 || changed.stdout.trim()
      || ignored.status !== 0 || ignored.stdout.split("\0").filter(Boolean).some(isContextPath)) {
    workflowError = "Startup commands changed the frozen repository. Install dependencies outside the checkout or in ignored environment directories.";
  }
}
await persistWorkflow();
for (const [index, step] of workflow.steps.entries()) {
  if (workflowError) break;
  if (Date.now() >= deadline) { workflowError = "Workflow timeout exhausted before the next step."; break; }
  if (cumulativeTokens >= request.model.max_tokens) { workflowError = "Workflow token budget exhausted before the next step."; break; }
  const record = { index: index + 1, name: step.name, promptHash: createHash("sha256").update(step.prompt).digest("hex"), status: "running" };
  steps.push(record); await persistWorkflow();
  if (request.workflow) {
    const marker = JSON.stringify({ type: "workflow_step_start", step: index + 1, name: step.name, promptHash: record.promptHash });
    trajectory.push(marker);
    liveWrites = liveWrites.then(() => appendFile(liveTrajectoryPath, `${marker}\n`, "utf8"));
  }
  const completed = await runPiStep({ request, prompt: step.prompt, env: setup.env, cwd: workspace,
    timeoutMs: deadline - Date.now(), remainingTokens: request.model.max_tokens - cumulativeTokens, redact,
    onRecord: (line) => {
      trajectory.push(line);
      liveWrites = liveWrites.then(() => appendFile(liveTrajectoryPath, `${line}\n`, "utf8"));
    },
  });
  cumulativeTokens += completed.cumulativeTokens;
  Object.assign(record, completed, { stderr: undefined });
  await appendFile(path.join(outputRoot, "agent.stderr.log"), completed.stderr, "utf8");
  if (completed.status !== "completed") workflowError = completed.promptError ?? `Prompt step ${index + 1} ${completed.status}.`;
  await persistWorkflow();
}
const lastStep = steps.at(-1);
const sessionStats = request.workflow ? aggregateStats(steps) : lastStep?.sessionStats ?? null;
const settled = !workflowError && steps.length === workflow.steps.length && !!lastStep?.settled;
const timedOut = setup.status === "timed-out" || steps.some((step) => step.timedOut) || !!workflowError?.includes("timeout");
const budgetExceeded = steps.some((step) => step.budgetExceeded) || cumulativeTokens >= request.model.max_tokens;
const budgetInterrupted = steps.some((step) => step.budgetInterrupted) || (steps.length < workflow.steps.length && budgetExceeded);
const promptError = steps.find((step) => step.promptError)?.promptError ?? null;
const exitCode = lastStep?.exitCode ?? setup.exitCode ?? 1;
await liveWrites;
await writeFile(path.join(outputRoot, "trajectory.jsonl"), `${trajectory.join("\n")}\n`, "utf8");
const completion = {
  ...argsReceipt,
  schemaVersion: 1, budgetProtocolVersion: 1, workflowProtocolVersion: 1, runId: request.runId,
  modelInvocations: steps.length, status: timedOut ? "timed-out" : "failed", exitCode,
  settled, budgetExceeded, budgetInterrupted, cumulativeTokens, sessionStats, promptError,
  workflowError: workflowError ?? "Final artifact validation did not complete.", workflowSteps: steps,
  changedFiles: [], contextPaths: [],
};
await writeFile(path.join(outputRoot, "result.json"), redact(JSON.stringify(completion, null, 2)), "utf8");
if (workflowError && steps.length === 0) process.exit(timedOut ? 124 : 1);

spawnSync("git", ["add", "-N", "--", "."], { cwd: workspace });
const git = (...args) => {
  const result = spawnSync("git", args, { cwd: workspace, encoding: "utf8", maxBuffer: 128 * 1024 * 1024 });
  if (result.status !== 0) throw new Error(`Git patch extraction failed: ${redact(result.stderr ?? String(result.error))}`);
  return result.stdout;
};
const changedFiles = git("diff", initialCommit, "--name-only", "-z", "--", ".").split("\0").filter(Boolean);
const changedContextPaths = changedFiles.filter(isContextPath);
const currentContextPaths = request.mode === "generate-context"
  ? [
      ...git("ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", ".").split("\0"),
      ...git("ls-files", "-z", "--others", "--ignored", "--exclude-standard", "--", ".").split("\0"),
    ].filter(Boolean).filter(isContextPath)
  : [];
const contextPaths = [...new Set([...changedContextPaths, ...currentContextPaths])].sort();

await writeFile(path.join(outputRoot, "raw_agent.patch"), redact(git("diff", initialCommit, "--binary", "--no-ext-diff", "--", ".")), "utf8");
const contextExclusions = contextPaths.map((relative) => `:(exclude,literal)${relative}`);
await writeFile(
  path.join(outputRoot, "graded.patch"),
  redact(git("diff", initialCommit, "--binary", "--no-ext-diff", "--", ".", ...contextExclusions)),
  "utf8",
);
await writeFile(
  path.join(outputRoot, "context_mutation.patch"),
  contextPaths.length
    ? redact(git("diff", initialCommit, "--binary", "--no-ext-diff", "--", ...contextPaths.map((relative) => `:(literal)${relative}`)))
    : "",
  "utf8",
);

let contextManifest = null;
if (request.mode === "generate-context") {
  const invalid = changedFiles.filter((file) => !isContextPath(file));
  if (invalid.length) throw new Error(`Context generator changed forbidden paths: ${invalid.join(", ")}`);
  const files = {};
  const deletedPaths = [];
  for (const relative of contextPaths) {
    const source = path.resolve(workspace, relative);
    if (!source.startsWith(`${workspace}${path.sep}`)) throw new Error(`Unsafe context path: ${relative}`);
    let stat;
    try {
      stat = await lstat(source);
    } catch (error) {
      if (error?.code === "ENOENT") {
        deletedPaths.push(relative.replaceAll("\\", "/"));
        continue;
      }
      throw error;
    }
    if (!stat.isFile() || stat.isSymbolicLink()) throw new Error(`Context path must be a regular file: ${relative}`);
    const destination = path.join(outputRoot, "context", "files", relative);
    await mkdir(path.dirname(destination), { recursive: true });
    await cp(source, destination, { dereference: false });
    files[relative.replaceAll("\\", "/")] = createHash("sha256").update(await readFile(source)).digest("hex");
  }
  contextManifest = { schemaVersion: 1, files, deletedPaths, capability, targetTaskSeen: false };
  await mkdir(path.join(outputRoot, "context"), { recursive: true });
  await writeFile(path.join(outputRoot, "context", "manifest.json"), JSON.stringify(contextManifest, null, 2), "utf8");
}

const result = {
  ...argsReceipt,
  schemaVersion: 1,
  budgetProtocolVersion: 1,
  runId: request.runId,
  status: timedOut ? "timed-out" : budgetExceeded && !settled ? "failed" : exitCode === 0 || settled ? "completed" : "failed",
  exitCode,
  settled,
  budgetExceeded,
  budgetInterrupted,
  promptError,
  cumulativeTokens,
  sessionStats,
  changedFiles,
  contextPaths,
  contextManifest,
  workflowProtocolVersion: 1,
  modelInvocations: steps.length,
  workflowError,
  workflowSteps: steps,
};
const emptyContextArtifact = request.mode === "generate-context"
  && Object.keys(contextManifest?.files ?? {}).length === 0;
result.emptyContextArtifact = emptyContextArtifact;
result.status = timedOut
  ? "timed-out"
  : workflowError || promptError || budgetInterrupted || emptyContextArtifact
    ? "failed"
    : exitCode === 0 || settled
      ? "completed"
      : "failed";
await writeFile(path.join(outputRoot, "result.json"), redact(JSON.stringify(result, null, 2)), "utf8");
process.exit(result.status === "completed" ? 0 : timedOut ? 124 : budgetExceeded ? 125 : 1);

function isContextPath(value) {
  const normalized = value.replaceAll("\\", "/").toLowerCase();
  const name = normalized.split("/").at(-1);
  return name === "agents.md"
    || name === "claude.md"
    || normalized === ".github/copilot-instructions.md"
    || normalized.startsWith(".ctx/")
    || (request.contextPaths ?? []).includes(value);
}
