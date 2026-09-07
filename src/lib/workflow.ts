import type { AgentWorkflow } from "../domain/types";

export const defaultWorkflow = (): AgentWorkflow => ({ setupCommands: [], steps: [{ name: "", prompt: null }] });

export function workflowError(workflow: AgentWorkflow): string | undefined {
  if (workflow.setupCommands.length > 20) return "A workflow supports up to 20 startup commands.";
  if (workflow.setupCommands.some((command) => !command.trim() || command.length > 20000 || command.includes("\0"))) return "Startup commands must be non-empty text without NUL characters.";
  if (!workflow.steps.length || workflow.steps.length > 50) return "A workflow requires between 1 and 50 prompt steps.";
  if (workflow.steps.some((step) => step.name.length > 120 || step.name.includes("\0"))) return "Step names must be text of at most 120 characters.";
  if (workflow.steps.some((step) => step.prompt !== null && (!step.prompt.trim() || step.prompt.length > 100000 || step.prompt.includes("\0")))) return "Custom step prompts must be non-empty text without NUL characters.";
}

export function moveWorkflowStep(workflow: AgentWorkflow, index: number, offset: number): AgentWorkflow {
  const target = index + offset;
  if (index < 0 || index >= workflow.steps.length || target < 0 || target >= workflow.steps.length) return workflow;
  const steps = [...workflow.steps];
  [steps[index], steps[target]] = [steps[target], steps[index]];
  return { ...workflow, steps };
}
