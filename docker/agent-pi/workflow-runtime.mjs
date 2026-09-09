import { spawn } from "node:child_process";
import { StringDecoder } from "node:string_decoder";
import { piAgentArgs } from "./agent-args.mjs";
import { consoleStream } from './console-stream.mjs';

const killTree = (child) => {
  try { process.kill(-child.pid, "SIGKILL"); } catch { child.kill("SIGKILL"); }
};

export async function runStartup(commands, { cwd, env, timeoutMs, redact, secrets = [], onOutput }) {
  if (!commands.length) return { status: "skipped", env, log: "", durationSeconds: 0 };
  const started = Date.now();
  // FD 3 is an in-memory environment handoff, never part of logs or artifacts.
  const child = spawn("/bin/bash", ["-e", "-o", "pipefail", "-c", `${commands.join("\n")}\n/usr/bin/env -0 >&3`],
    { cwd, env, detached: true, stdio: ["ignore", "pipe", "pipe", "pipe"] });
  let stdout = "", stderr = "", environment = "", timedOut = false, failure;
  const outDecoder = new StringDecoder("utf8"), errDecoder = new StringDecoder("utf8"), envDecoder = new StringDecoder("utf8");
  const liveOut = consoleStream(secrets, onOutput), liveErr = consoleStream(secrets, onOutput);
  child.stdout.on("data", (chunk) => { stdout += outDecoder.write(chunk); liveOut.write(chunk); });
  child.stderr.on("data", (chunk) => { stderr += errDecoder.write(chunk); liveErr.write(chunk); });
  child.stdio[3].on("data", (chunk) => { environment += envDecoder.write(chunk); });
  child.on("error", (error) => { failure = redact(error.message); });
  const timer = setTimeout(() => { timedOut = true; killTree(child); }, Math.max(1, timeoutMs));
  const exitCode = await new Promise((resolve) => child.on("close", (code) => resolve(code ?? 1)));
  clearTimeout(timer);
  stdout += outDecoder.end(); stderr += errDecoder.end();
  liveOut.end(); liveErr.end();
  environment += envDecoder.end();
  const nextEnv = Object.fromEntries(environment.split("\0").filter(Boolean).map((item) => {
    const separator = item.indexOf("=");
    return [item.slice(0, separator), item.slice(separator + 1)];
  }));
  const status = timedOut ? "timed-out" : exitCode === 0 && environment ? "completed" : "failed";
  return { status, exitCode, env: status === "completed" ? nextEnv : env,
    log: redact(`${stdout}${stderr}`), durationSeconds: (Date.now() - started) / 1000,
    error: failure ?? (status === "failed" ? "Startup commands failed or did not return their environment." : null) };
}

export async function runPiStep({ request, prompt, env, cwd, timeoutMs, remainingTokens, redact, onRecord, secrets = [], onOutput }) {
  let executable = "pi";
  let args = ["--mode", "rpc", "--no-session", "--no-extensions", "--no-skills", "--no-prompt-templates",
    "--no-approve", "--offline", "--provider", request.model.provider, "--model", request.model.model];
  if (request.model.provider === "mock") {
    executable = process.execPath; args = ["/opt/ctxbench/mock-pi.mjs", request.mode];
  } else if (request.mode === "generate-context") {
    args.push("--skill", "/home/ctxbench/.pi/agent/skills/ctxbench-generate-context/SKILL.md");
  }
  // argv is passed literally: no shell, quoting, interpolation or prompt injection.
  args.push(...piAgentArgs(request.agentArgs));
  const started = Date.now();
  const agent = spawn(executable, args, { cwd, env, detached: true, stdio: ["pipe", "pipe", "pipe"] });
  const send = (command) => { if (!agent.stdin.destroyed) agent.stdin.write(`${JSON.stringify(command)}\n`); };
  const decoder = new StringDecoder("utf8"), errDecoder = new StringDecoder("utf8");
  const liveErr = consoleStream(secrets, onOutput);
  let buffer = "", stderr = "", sessionStats = null, settled = false, timedOut = false;
  let cumulativeTokens = 0, budgetExceeded = false, budgetInterrupted = false, promptError = null;
  agent.stdin.on("error", () => {});
  agent.on("error", (error) => { promptError = redact(error.message); });
  const consume = (line) => {
    if (!line) return;
    onRecord(redact(line));
    let event;
    try { event = JSON.parse(line); } catch { return; }
    if (event.type === "extension_ui_request" && ["select", "confirm", "input", "editor"].includes(event.method)) {
      send({ type: "extension_ui_response", id: event.id, cancelled: true });
    }
    if (event.type === "message_end" && event.message?.role === "assistant" && event.message.usage) {
      const usage = event.message.usage;
      cumulativeTokens += Number(usage.totalTokens ?? (usage.input ?? 0) + (usage.output ?? 0) + (usage.cacheRead ?? 0) + (usage.cacheWrite ?? 0));
      if (cumulativeTokens >= remainingTokens && !budgetExceeded) {
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
      settled = true; send({ id: "ctxbench-stats", type: "get_session_stats" });
    }
    if (event.type === "response" && event.id === "ctxbench-stats") {
      sessionStats = event.success ? event.data : null; agent.kill("SIGTERM");
    }
  };
  agent.stdout.on("data", (chunk) => {
    buffer += decoder.write(chunk);
    for (;;) {
      const newline = buffer.indexOf("\n");
      if (newline < 0) break;
      consume(buffer.slice(0, newline).replace(/\r$/, "")); buffer = buffer.slice(newline + 1);
    }
  });
  agent.stderr.on("data", (chunk) => { stderr += errDecoder.write(chunk); liveErr.write(chunk); });
  const timer = setTimeout(() => { timedOut = true; killTree(agent); }, Math.max(1, timeoutMs));
  if (request.model.thinking) send({ type: "set_thinking_level", level: request.model.thinking });
  send({ id: "ctxbench-prompt", type: "prompt", message: prompt });
  const exitCode = await new Promise((resolve) => agent.on("close", (code) => resolve(code ?? 1)));
  clearTimeout(timer);
  // Reap helper processes before the next fresh session starts in this same container.
  killTree(agent);
  buffer += decoder.end(); if (buffer) consume(buffer.replace(/\r$/, ""));
  stderr += errDecoder.end();
  liveErr.end();
  return { status: timedOut ? "timed-out" : promptError || budgetInterrupted || !(exitCode === 0 || settled) ? "failed" : "completed",
    exitCode, settled, timedOut, budgetExceeded, budgetInterrupted, cumulativeTokens,
    promptError: promptError ? redact(String(promptError)) : null, sessionStats,
    stderr: redact(stderr), durationSeconds: (Date.now() - started) / 1000 };
}

export function aggregateStats(steps) {
  const tokens = { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 };
  let cost = 0, hasCost = false;
  for (const step of steps) {
    const stats = step.sessionStats ?? {}, nested = stats.tokens ?? {};
    tokens.input += Number(stats.inputTokens ?? nested.input ?? 0);
    tokens.output += Number(stats.outputTokens ?? nested.output ?? 0);
    tokens.cacheRead += Number(nested.cacheRead ?? 0); tokens.cacheWrite += Number(nested.cacheWrite ?? 0);
    tokens.total += step.cumulativeTokens;
    const reported = typeof stats.cost === "object" ? stats.cost?.total : stats.cost ?? stats.totalCost;
    if (typeof reported === "number") { cost += reported; hasCost = true; }
  }
  return { tokens, ...(hasCost ? { cost } : {}) };
}
