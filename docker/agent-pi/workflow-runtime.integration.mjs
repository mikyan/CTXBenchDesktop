import assert from "node:assert/strict";
// Linux-only Node tests, invoked explicitly with node --test inside the agent image.
import test from "node:test";
import { aggregateStats, runPiStep, runStartup } from "./workflow-runtime.mjs";
import { piAgentArgs } from "./agent-args.mjs";

const options = { cwd: "/tmp", env: { ...process.env, FIXTURE_SECRET: "synthetic-secret" }, timeoutMs: 3000,
  redact: (text) => text.replaceAll("synthetic-secret", "[REDACTED]") };

test("the preinstalled Pi CLI accepts the extra flags without changing protocol or prompts", async () => {
  const { parseArgs } = await import('/usr/local/lib/node_modules/@earendil-works/pi-coding-agent/dist/cli/args.js');
  const extra = piAgentArgs(['--tools', 'read, bash', '--exclude-tools', 'write', '--verbose']);
  const parsed = parseArgs(['--mode', 'rpc', '--no-session', '--no-extensions', '--no-skills', '--no-prompt-templates',
    '--no-approve', '--offline', '--provider', 'fixture-provider', '--model', 'fixture-model', ...extra]);
  assert.equal(parsed.mode, 'rpc');
  assert.equal(parsed.provider, 'fixture-provider');
  assert.equal(parsed.model, 'fixture-model');
  assert.equal(parsed.noSession, true);
  assert.deepEqual(parsed.tools, ['read', 'bash']);
  assert.deepEqual(parsed.excludeTools, ['write']);
  assert.deepEqual(parsed.messages, []);
  assert.deepEqual(parsed.fileArgs, []);
  assert.deepEqual(parsed.diagnostics, []);
  assert.equal(parsed.unknownFlags.size, 0);
});

test("each agent subprocess receives literal ordered argv with no shell expansion", async () => {
  const args = ['--tools', 'read, bash', '--exclude-tools', '$(echo literal); 中文', '--verbose'];
  const result = await runPiStep({ request: { mode: 'grade', agentArgs: args, model: { provider: 'mock', model: 'deterministic', thinking: 'off' } },
    prompt: 'CTXBENCH_WORKFLOW_TEST:' + JSON.stringify({ expectedArgs: args }), env: process.env, cwd: '/tmp',
    timeoutMs: 3000, remainingTokens: 1000, redact: (text) => text, onRecord: () => {} });
  assert.equal(result.status, 'completed');
  assert.equal(result.promptError, null);
});

test("startup retains exports and keeps the environment handoff out of logs", async () => {
  const result = await runStartup(['export WORKFLOW_TEST_VALUE="中文=literal value"', 'printf "%s" "$FIXTURE_SECRET"'], options);
  assert.equal(result.status, "completed");
  assert.equal(result.env.WORKFLOW_TEST_VALUE, "中文=literal value");
  assert.equal(result.log, "[REDACTED]");
  assert.ok(!result.log.includes("FIXTURE_SECRET="));
});

test("startup stops on failure and rejects early exit without environment handoff", async () => {
  const result = await runStartup(['false', 'printf should-not-run'], options);
  assert.equal(result.status, "failed");
  assert.ok(!result.log.includes("should-not-run"));
  assert.equal((await runStartup(['exit 0'], options)).status, "failed");
});

test("startup timeout reaps the shell and its child", async () => {
  const result = await runStartup(['sleep 10'], { ...options, timeoutMs: 100 });
  assert.equal(result.status, "timed-out");
  assert.ok(result.durationSeconds < 3);
});

test('startup console is visible before completion, redacted, without the environment handoff', async () => {
  let completed = false, output = '';
  let ready;
  const firstOutput = new Promise((resolve) => { ready = resolve; });
  const running = runStartup(['printf "READY %s\\n" "$FIXTURE_SECRET"', 'sleep 1', 'printf "DONE\\n"'], {
    ...options, secrets: ['synthetic-secret'], onOutput: (text) => { output += text; ready(); },
  }).then((result) => { completed = true; return result; });
  await firstOutput;
  assert.equal(completed, false);
  assert(output.startsWith('READY [REDACTED]'));
  const result = await running;
  assert.equal(result.status, 'completed');
  assert.equal(output, 'READY [REDACTED]\nDONE\n');
  assert(!output.includes('FIXTURE_SECRET='));
});

test("agent timeout terminates a fresh session", async () => {
  const result = await runPiStep({ request: { mode: 'grade', model: { provider: 'mock', model: 'deterministic', thinking: 'off' } },
    prompt: 'timeout fixture', env: { ...process.env, CTXBENCH_TEST_DELAY_SECONDS: '10' }, cwd: '/tmp',
    timeoutMs: 100, remainingTokens: 1000, redact: (text) => text, onRecord: () => {} });
  assert.equal(result.status, 'timed-out');
  assert.ok(result.durationSeconds < 3);
});

test("aggregate usage covers every session without multiplying the allowance", () => {
  const stats = aggregateStats([
    { cumulativeTokens: 7, sessionStats: { inputTokens: 5, outputTokens: 2, cost: 1 } },
    { cumulativeTokens: 13, sessionStats: { tokens: { input: 6, output: 3, cacheRead: 4 }, totalCost: 2 } },
  ]);
  assert.deepEqual(stats, { tokens: { input: 11, output: 5, cacheRead: 4, cacheWrite: 0, total: 20 }, cost: 3 });
});
