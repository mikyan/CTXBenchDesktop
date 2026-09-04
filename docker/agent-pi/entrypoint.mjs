import { createHash } from "node:crypto";
import { spawn, spawnSync } from "node:child_process";
import { StringDecoder } from "node:string_decoder";
import { cp, lstat, mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";

const requestPath = "/ctxbench/request.json";
const outputRoot = "/ctxbench/output";
const workspace = "/workspace";

const request = JSON.parse(await readFile(requestPath, "utf8"));
if (request.schemaVersion !== 1 || !request.runId || !request.prompt || !request.model) {
  throw new Error("Invalid CTXBench agent request.");
}

await mkdir(outputRoot, { recursive: true });
spawnSync("git", ["config", "--global", "--add", "safe.directory", workspace]);

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
let cumulativeTokens = 0;

let executable = "pi";
let args = [
  "--mode", "rpc",
  "--no-session",
  "--no-extensions",
  "--no-skills",
  "--no-prompt-templates",
  "--no-approve",
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
      usage.totalTokens ?? usage.input + usage.output + usage.cacheRead + usage.cacheWrite,
    );
    if (cumulativeTokens >= request.model.max_tokens && !budgetExceeded) {
      budgetExceeded = true;
      send({ type: "abort" });
    }
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
const prompt = request.mode === "generate-context"
  ? `/skill:ctxbench-generate-context\n\nCapability: ${capability}. Generate a frozen repository context artifact from this exact baseline checkout.`
  : request.prompt;

if (request.model.thinking && request.model.thinking !== "off") {
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
const git = (...args) => spawnSync("git", args, { cwd: workspace, encoding: "utf8", maxBuffer: 128 * 1024 * 1024 }).stdout ?? "";
const changedFiles = git("diff", "--name-only", "--", ".").split("\n").map((item) => item.trim()).filter(Boolean);
const contextPaths = changedFiles.filter(isContextPath);

await writeFile(path.join(outputRoot, "raw_agent.patch"), git("diff", "--binary", "--no-ext-diff", "--", "."), "utf8");
const contextExclusions = contextPaths.map((relative) => `:(exclude,literal)${relative}`);
await writeFile(
  path.join(outputRoot, "graded.patch"),
  git("diff", "--binary", "--no-ext-diff", "--", ".", ...contextExclusions),
  "utf8",
);
await writeFile(
  path.join(outputRoot, "context_mutation.patch"),
  contextPaths.length
    ? git("diff", "--binary", "--no-ext-diff", "--", ...contextPaths.map((relative) => `:(literal)${relative}`))
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
  cumulativeTokens,
  sessionStats,
  changedFiles,
  contextPaths,
  contextManifest,
};
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
