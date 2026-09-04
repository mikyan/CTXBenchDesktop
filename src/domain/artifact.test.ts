import { describe, expect, it } from "vitest";
import { canonicalArtifactIdentity, contextArtifactKey } from "./artifact";

describe("contextArtifactKey", () => {
  it("is stable and content-addressed", async () => {
    const identity = {
      repository: "org/repo",
      commit: "abc123",
      capability: "tree-only" as const,
      skillVersion: "1.0.0",
      generationPromptHash: "prompt-sha",
      builder: { provider: "openai", model: "model-a", thinking: "high" as const, maxTokens: 8192 },
    };
    const first = await contextArtifactKey(identity);
    const second = await contextArtifactKey({ ...identity, builder: { ...identity.builder } });
    expect(first).toEqual(second);
    expect(first).toMatch(/^[a-f0-9]{64}$/);
    expect(canonicalArtifactIdentity(identity)).toContain('"commit":"abc123"');
  });
});
