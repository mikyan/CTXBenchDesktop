import type { Page } from "../app-types";

export const pageLabels: Record<Page, string> = {
  overview: "Overview", experiments: "Experiments", datasets: "Datasets",
  knowledge: "Knowledge", constraints: "Constraints", infrastructure: "Settings",
};
export const settingsSections = [
  { id: "runtime", label: "Runtime & diagnostics", description: "WSL distribution, worker status and troubleshooting", group: "Connection" },
  { id: "credentials", label: "Model credentials", description: "API keys and allowlisted environment variables", group: "Connection" },
  { id: "images", label: "Application images", description: "Install, build or export the four runtime images", group: "Deployment" },
  { id: "profiles", label: "Company profiles", description: "Reusable model, image and Git mirror settings", group: "Company customization" },
  { id: "adaptation", label: "Image adaptation", description: "Install company dependencies in a new image", group: "Company customization" },
  { id: "resources", label: "Resource migration", description: "Transfer custom datasets, baselines and frozen contexts", group: "Company customization" },
] as const;
export type SettingsSection = typeof settingsSections[number]["id"];

export const experimentViews = [
  { id: "plans", label: "Experiment plans" },
  { id: "results", label: "Results & evidence" },
  { id: "budgets", label: "Token budgets" },
] as const;
