import { createHash } from "node:crypto";
import { spawn, spawnSync } from "node:child_process";
import { StringDecoder } from "node:string_decoder";
import { appendFile, cp, lstat, mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";

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
  .filter(([name, value]) => value && /(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)/i.test(name))
  .map(([, value]) => value)
  .filter((value) => value.length >= 8)
  .sort((left, right) => right.length - left.length);

const redact = (value) => secretValues.reduce((text, secret) => text.replaceAll(secret, "[REDACTED]"), value);
const trajectory = [];
let sessionStats = null;
let settled = false;
let timedOut = false;
let budgetExceeded = false;
let budgetInterrupted = false;
let cumulativeTokens = 0;
let promptError = null;

let executable = "pi";
let args = [
  "--mode", "rpc",
  "--no-session",
  "--no-extensions",
  "--no-skills",
  "--no-prompt-templates",
  "--no-approve",
  "--offline",
  "--provider", request.model.provider,
  "--model", request.model.model,
];
if (request.model.provider === "mock") {
  executable = "node";
  args = ["/opt/ctxbench/mock-pi.mjs", request.mode];
} else if (request.mode === "generate-context") {
  args.push("--skill", "/home/ctxbench/.pi/agent/skills/ctxbench-generate-context/SKILL.md");
}
const agent = spawn(executable, args, {
  cwd: workspace,
  env: process.env,
  stdio: ["pipe", "pipe", "pipe"],
});

const send = (command) => agent.stdin.write(`${JSON.stringify(command)}\n`);
const decoder = new StringDecoder("utf8");
let buffer = "";

function onRecord(line) {
  if (!line) return;
  const safeLine = redact(line);
  trajectory.push(safeLine);
  void appendFile(liveTrajectoryPath, `${safeLine}\n`, "utf8");
  let event;
  try {
    event = JSON.parse(line);
  } catch {
    return;
  }
  if (event.type === "extension_ui_request" && ["select", "confirm", "input", "editor"].includes(event.method)) {
    send({ type: "extension_ui_response", id: event.id, cancelled: true });
  }
  if (event.type === "message_end" && event.message?.role === "assistant" && event.message.usage) {
    const usage = event.message.usage;
    cumulativeTokens += Number(
      usage.totalTokens ?? (usage.input ?? 0) + (usage.output ?? 0) + (usage.cacheRead ?? 0) + (usage.cacheWrite ?? 0),
    );
    if (cumulativeTokens >= request.model.max_tokens && !budgetExceeded) {
      budgetExceeded = true;
      budgetInterrupted = !["stop", "end_turn"].includes(event.message.stopReason);
      send({ type: "abort" });
    }
  }
  if (event.type === "response" && event.id === "ctxbench-prompt" && !event.success) {
    promptError = event.error ?? "Pi rejected the benchmark prompt.";
    agent.kill("SIGTERM");
  }
  if (event.type === "agent_settled" && !settled) {
    settled = true;
    send({ id: "ctxbench-stats", type: "get_session_stats" });
  }
  if (event.type === "response" && event.id === "ctxbench-stats") {
    sessionStats = event.success ? event.data : null;
    agent.kill("SIGTERM");
  }
}

agent.stdout.on("data", (chunk) => {
  buffer += decoder.write(chunk);
  for (;;) {
    const newline = buffer.indexOf("\n");
    if (newline < 0) break;
    let line = buffer.slice(0, newline);
    buffer = buffer.slice(newline + 1);
    if (line.endsWith("\r")) line = line.slice(0, -1);
    onRecord(line);
  }
});

let stderr = "";
agent.stderr.on("data", (chunk) => { stderr += redact(chunk.toString("utf8")); });

const timeout = setTimeout(() => {
  timedOut = true;
  send({ type: "abort" });
  setTimeout(() => agent.kill("SIGKILL"), 5_000).unref();
}, Math.max(1, request.timeoutSeconds ?? 2700) * 1000);

const capability = request.metadata?.capability ?? "tree-only";
const prompt = request.prompt;

if (request.model.thinking) {
  send({ type: "set_thinking_level", level: request.model.thinking });
}
send({ id: "ctxbench-prompt", type: "prompt", message: prompt });

const exitCode = await new Promise((resolve) => agent.on("close", (code) => resolve(code ?? 1)));
clearTimeout(timeout);
buffer += decoder.end();
if (buffer) onRecord(buffer.endsWith("\r") ? buffer.slice(0, -1) : buffer);

await writeFile(path.join(outputRoot, "trajectory.jsonl"), `${trajectory.join("\n")}\n`, "utf8");
await writeFile(path.join(outputRoot, "agent.stderr.log"), stderr, "utf8");

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
  schemaVersion: 1,
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
};
const emptyContextArtifact = request.mode === "generate-context"
  && Object.keys(contextManifest?.files ?? {}).length === 0;
result.emptyContextArtifact = emptyContextArtifact;
result.status = timedOut
  ? "timed-out"
  : promptError || budgetInterrupted || emptyContextArtifact
    ? "failed"
    : exitCode === 0 || settled
      ? "completed"
      : "failed";
await writeFile(path.join(outputRoot, "result.json"), JSON.stringify(result, null, 2), "utf8");
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
