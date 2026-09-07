import { describe, expect, it } from "vitest";
import { environmentNamesError, parseEnvironmentNames, runtimeVariablesPayload } from "./environment";

describe("agent environment names", () => {
  it("supports multiple names, common separators and deduplication", () => {
    expect(parseEnvironmentNames("OPENAI_API_KEY\r\nOPENAI_BASE_URL, ANTHROPIC_API_KEY，AWS_REGION；AWS_SESSION_TOKEN;OPENAI_API_KEY"))
      .toEqual(["OPENAI_API_KEY", "OPENAI_BASE_URL", "ANTHROPIC_API_KEY", "AWS_REGION", "AWS_SESSION_TOKEN"]);
    expect(parseEnvironmentNames(" ,\n ")).toEqual([]);
  });
  it("rejects values in experiment names and does not echo them in errors", () => {
    expect(environmentNamesError("OPENAI_API_KEY=fixture-not-a-real-key"))
      .toBe("Enter variable names only; save values in Infrastructure.");
    expect(environmentNamesError("invalid-name")).toBeDefined();
    expect(environmentNamesError("OPENAI_API_KEY\nOPENAI_BASE_URL")).toBeUndefined();
  });
});

describe("runtime variable batches", () => {
  it("preserves values literally while trimming names and ignoring fully blank rows", () => {
    expect(runtimeVariablesPayload([
      { name: " OPENAI_API_KEY ", value: "fixture-key=with,$special;characters " },
      { name: "OPENAI_BASE_URL", value: "https://provider.invalid/v1?foo=bar" },
      { name: " ", value: "" },
    ])).toEqual({ variables: [
      { name: "OPENAI_API_KEY", value: "fixture-key=with,$special;characters " },
      { name: "OPENAI_BASE_URL", value: "https://provider.invalid/v1?foo=bar" },
    ] });
  });
  it("rejects duplicate and incomplete rows without including values in errors", () => {
    expect(() => runtimeVariablesPayload([{ name: "KEY_NAME", value: "first" }, { name: "KEY_NAME", value: "second" }]))
      .toThrow("Each environment variable name must be unique.");
    for (const row of [{ name: "", value: "fixture-key" }, { name: "KEY_NAME", value: "" }, { name: "KEY_NAME", value: "fixture\0key" }]) {
      expect(() => runtimeVariablesPayload([row])).toThrow();
      try { runtimeVariablesPayload([row]); } catch (error) { expect(String(error)).not.toContain("fixture"); }
    }
  });
  it("bounds batch size", () => {
    expect(() => runtimeVariablesPayload([])).toThrow("Enter between 1 and 100 environment variables.");
    expect(() => runtimeVariablesPayload(Array.from({ length: 101 }, (_, index) => ({ name: `KEY_${index}`, value: "fixture" }))))
      .toThrow("Enter between 1 and 100 environment variables.");
  });
});
