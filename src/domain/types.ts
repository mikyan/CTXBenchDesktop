export type BenchmarkKind = "swebench" | "ctxbench" | "custom";
export type ContextArm = "none" | "skill-generated" | "manual" | "developer-historical";
export type ExperimentStatus = "draft" | "preparing" | "ready" | "running" | "paused" | "completed" | "failed" | "cancelled";
export type RunStatus = "queued" | "preparing" | "running" | "grading" | "completed" | "failed" | "cancelled";
export type ConstraintVerdict = "satisfied" | "violated" | "neutral";
export type KnowledgeCapability = "tree-only" | "history-aware" | "task-informed";

export interface FrozenModelConfig {
  provider: string;
  model: string;
  thinking: "off" | "minimal" | "low" | "medium" | "high" | "xhigh" | "max";
  maxTokens: number;
  temperature?: number;
}

export interface EvaluationProfiles {
  builder: FrozenModelConfig;
  solver: FrozenModelConfig;
  constraintMiner: FrozenModelConfig;
  constraintJudge: FrozenModelConfig;
}

export interface ResourcePolicy {
  cpus: number;
  memoryGb: number;
  timeoutMinutes: number;
  network: "offline" | "api-only" | "unrestricted";
}

export interface Experiment {
  id: string;
  name: string;
  benchmark: BenchmarkKind;
  dataset: string;
  status: ExperimentStatus;
  arms: ContextArm[];
  repeats: number;
  tasks: number;
  completedRuns: number;
  totalRuns: number;
  createdAt: string;
  updatedAt: string;
  model: FrozenModelConfig;
  profiles: EvaluationProfiles;
  agentImage: string;
  resources: ResourcePolicy;
  seed: number;
}

export interface PlannedRun {
  id: string;
  experimentId: string;
  pairId: string;
  taskId: string;
  repeat: number;
  arm: ContextArm;
  ordinal: number;
  status: RunStatus;
}

export interface BenchmarkRun extends PlannedRun {
  repository: string;
  commit: string;
  startedAt?: string;
  updatedAt?: string;
  durationSeconds?: number;
  testsPassed?: boolean;
  constraintVerdict?: ConstraintVerdict;
  inputTokens?: number;
  outputTokens?: number;
  costUsd?: number;
  contextArtifactId?: string;
  contextMutated?: boolean;
  failure?: string;
  pairingHash?: string;
  agentImageDigest?: string;
  promptHash?: string;
  solverRunId?: string;
  outputDir?: string;
  mock?: boolean;
  constraintQuality?: "silver" | "gold";
  judgeRecords?: unknown[];
  grade?: unknown;
}

export interface KnowledgeArtifact {
  id: string;
  repository: string;
  commit: string;
  capability: KnowledgeCapability;
  source: Exclude<ContextArm, "none">;
  files: number;
  bytes: number;
  tasksReused: number;
  status: "ready" | "generating" | "invalid";
  generatedAt?: string;
  builder: FrozenModelConfig;
  promptHash: string;
  skillVersion: string;
  informed: boolean;
  filePaths?: string[];
}

export interface ConstraintRecord {
  id: string;
  repository: string;
  title: string;
  rationale: string;
  provenance: string;
  quality: "silver" | "gold";
  applicableRuns: number;
  satisfied: number;
  violated: number;
  neutral: number;
}

export interface ArmMetric {
  arm: ContextArm;
  runs: number;
  passRate: number;
  passCount: number;
  violationRate: number;
  avgDurationSeconds: number;
  avgCostUsd: number;
}

export interface DashboardMetrics {
  totalRuns: number;
  passRate: number;
  knowledgeLift: number;
  passPatchViolationRate: number;
  avgCostUsd: number;
  pairedWins: number;
  pairedLosses: number;
  pairedTies: number;
  dsr: number;
  dvr: number;
  dnr: number;
  judgedRuns?: number;
  passingApplicable?: number;
  failedRuns?: number;
}

export interface DiagnosticItem {
  id: "wsl" | "distribution" | "docker" | "worker" | "storage";
  label: string;
  status: "healthy" | "warning" | "missing" | "checking";
  detail: string;
  fix?: string;
}

export interface ActivityItem {
  id: string;
  kind: "run" | "artifact" | "constraint" | "system";
  message: string;
  detail: string;
  timestamp: string;
}

export interface DashboardSnapshot {
  metrics: DashboardMetrics;
  armMetrics: ArmMetric[];
  experiments: Experiment[];
  runs: BenchmarkRun[];
  artifacts: KnowledgeArtifact[];
  constraints: ConstraintRecord[];
  diagnostics: DiagnosticItem[];
  activity: ActivityItem[];
  runtime: "desktop" | "mock";
  runner?: string;
  datasets?: DatasetRecord[];
  operations?: OperationRecord[];
}

export interface CreateExperimentRequest {
  name: string;
  benchmark: BenchmarkKind;
  dataset: string;
  arms: ContextArm[];
  repeats: number;
  taskIds: string[];
  model: FrozenModelConfig;
  profiles: EvaluationProfiles;
  agentImage: string;
  resources: ResourcePolicy;
  seed: number;
  envNames?: string[];
  contextArtifacts?: Record<string, string>;
  prepareOnly?: boolean;
  evaluateConstraints?: boolean;
  judgeProfiles?: FrozenModelConfig[];
  constraintPackages?: Record<string, string>;
}

export interface DatasetRecord { id: string; name: string; benchmark: BenchmarkKind; count: number; createdAt: string }
export interface TaskSummary { id: string; repository: string; baseCommit: string; prompt: string; image?: string }
export interface OperationRecord { id: string; kind: string; status: string; createdAt: string; updatedAt: string; failure?: string }
export interface RuntimeSettings { runner: string; dataDirectory: string; credentials: { name: string; configured: boolean }[]; datasetFiles: string[] }
