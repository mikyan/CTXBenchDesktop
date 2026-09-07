import { describe, expect, it } from "vitest";
import { createHash } from "node:crypto";
import { piAgentArgs, agentArgsReceipt } from "../../docker/agent-pi/agent-args.mjs";

describe("Pi startup argument protocol", () => {
  it("keeps literal values and returns a stable UTF-8 receipt", () => {
    const args = ["--tools", "read, bash", "--exclude-tools", "工具", "--verbose"];
    expect(piAgentArgs(args)).toEqual(args);
    expect(piAgentArgs()).toEqual([]);
    expect(agentArgsReceipt(args)).toEqual({ agentArgsProtocolVersion: 1, agentArgsHash: createHash("sha256").update(JSON.stringify(args)).digest("hex") });
  });
  it("cannot override benchmark-controlled flags, prompts or credentials", () => {
    for (const args of [["--model", "another"], ["--mode=rpc"], ["-p", "prompt"], ["--", "prompt"], ["@AGENTS.md"], ["--skill", "file"], ["--resume"], ["--api-key", "fixture-secret"], ["--extension", "file"], ["--tools"], ["--tools", "--model"], ["--unknown"], ["--verbose\0"], null, [3]]) {
      expect(() => piAgentArgs(args)).toThrow();
      try { piAgentArgs(args); } catch (error) { expect(error.message).not.toContain("fixture-secret"); }
    }
  });
});
