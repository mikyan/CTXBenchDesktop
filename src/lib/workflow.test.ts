import { describe, expect, it } from "vitest";
import { defaultWorkflow, moveWorkflowStep, workflowError } from "./workflow";
import { translate } from "../i18n";

describe("workflow configuration", () => {
  it("starts with one default prompt and no startup commands", () => {
    expect(defaultWorkflow()).toEqual({ setupCommands: [], steps: [{ name: "", prompt: null }] });
    expect(workflowError(defaultWorkflow())).toBeUndefined();
  });
  it("reorders steps without mutating the source or their individual prompts", () => {
    const workflow = { setupCommands: ["npm ci"], steps: [{ name: "Plan", prompt: "Plan {{default_prompt}}" }, { name: "Code", prompt: "Implement the plan" }] };
    expect(moveWorkflowStep(workflow, 1, -1).steps.map((step) => step.name)).toEqual(["Code", "Plan"]);
    expect(workflow.steps[0].name).toBe("Plan");
    expect(moveWorkflowStep(workflow, 0, -1)).toBe(workflow);
  });
  it("rejects empty custom prompts, empty commands and empty workflows", () => {
    expect(workflowError({ setupCommands: [], steps: [{ name: "", prompt: " " }] })).toBeDefined();
    expect(workflowError({ ...defaultWorkflow(), setupCommands: [""] })).toBeDefined();
    expect(workflowError({ setupCommands: [], steps: [] })).toBeDefined();
  });
  it("keeps the default prompt placeholder literal in both languages", () => {
    const key = "Use {{default_prompt}} to include the existing generation instruction or the current task prompt. No conversation history is passed between steps; only repository files are shared.";
    expect(translate("zh-CN", key)).toContain("{{default_prompt}}");
    expect(translate("en", key)).toContain("{{default_prompt}}");
    expect(translate("zh-CN", "{count} prompt steps", { count: 3 })).toBe("3 个 Prompt 步骤");
  });
});
