import { z } from "zod";

export const companyProfileSchema = z.object({
  format: z.literal("ctxbench-company-profile"), version: z.literal(1), name: z.string(),
  agentImage: z.string(), harnessImage: z.string(), provider: z.string(), model: z.string(),
  envNames: z.array(z.string()), agentArgs: z.array(z.string()), offline: z.boolean(),
  gitMirrors: z.array(z.object({ repository: z.string(), mirror: z.string() }).strict()),
  providerDomains: z.array(z.string()),
  imageMappings: z.array(z.object({ source: z.string(), target: z.string() }).strict()).optional(),
}).strict();
export type CompanyProfile = z.infer<typeof companyProfileSchema>;
export interface CompanyProfileRecord { id: string; createdAt: string; document: CompanyProfile }
export interface OperatorJob {
  diagnostic?: import('../domain/types').FailureDiagnostic;
  id: string; kind: string; status: string; failure?: string;
  progress?: { percent?: number; log: string; updatedAt: string };
  result?: { filename?: string; path?: string; sha256?: string; imageId?: string; tag?: string; note?: string;
    inspection?: ResourceInspection;
    reports?: { taskId: string; candidateReady: boolean; failure?: string; phases: Record<string, { exitCode: number; resolved: boolean; log: string; infrastructureError: boolean }> }[] };
}
export interface ResourceInspection { filename: string; sha256: string; dataset: string; datasetId: string; images: number; baselines: number; contexts: number; conflicts: string[]; requiredBytes: number; freeBytes: number; ready: boolean }
export interface IntranetInventory {
  hostTransferDirectory?: string | null;
  profiles: CompanyProfileRecord[]; operations: OperatorJob[]; transferDirectory: string;
  drafts: { id: string; name: string; createdAt: string }[];
  adaptations: { id: string; name: string; imageId: string; tag: string }[];
}
export const defaultCompanyProfile = (): CompanyProfile => ({
  format: "ctxbench-company-profile", version: 1, name: "", agentImage: "ctxbench/agent-pi:0.1.0",
  harnessImage: "ctxbench/official-harness:0.1.0", provider: "", model: "", envNames: [], agentArgs: [],
  offline: true, gitMirrors: [], providerDomains: [],
});
export function namesFromLines(value: string) { return [...new Set(value.split(/[\s,]+/).filter(Boolean))]; }
export function terminalOperatorJob(status: string) { return ["completed", "failed", "cancelled", "paused"].includes(status); }
export function operatorKindLabel(kind: string) {
  return ({ "intranet:probe": "Dataset self-test", "intranet:image-build": "Image adaptation",
    'intranet:image-pull': 'Pull an existing image',
    "intranet:standard-images": "Project image installation",
    "intranet:image-check": "Registry availability check",
    "intranet:bundle-export": "Resource bundle export", "intranet:bundle-import": "Resource bundle import", "intranet:bundle-inspect": "Resource bundle verification" } as Record<string, string>)[kind] ?? kind;
}
export async function buildFiles(files: FileList | File[]): Promise<{ path: string; base64: string }[]> {
  const selected = Array.from(files);
  if (selected.reduce((sum, file) => sum + file.size, 0) > 30 * 1024 * 1024 || selected.length > 200) throw Error("Build uploads are limited to 30 MiB and 200 files.");
  if (new Set(selected.map((file) => file.name)).size !== selected.length) throw Error("Build filenames must be unique.");
  return Promise.all(selected.map(async (file) => {
    const bytes = new Uint8Array(await file.arrayBuffer());
    let binary = "";
    for (let i = 0; i < bytes.length; i += 8192) binary += String.fromCharCode(...bytes.subarray(i, i + 8192));
    return { path: file.name, base64: btoa(binary) };
  }));
}
export function companyFeatureError(cause: unknown): string {
  const message = cause instanceof Error ? cause.message : String(cause);
  return /^(?:Error: )?Not Found$/i.test(message) ? "Company features require a newer Worker image. Install the matching image in Settings → Application images, then restart the Worker after pausing experiments. Existing results remain available; new configuration features require an upgrade." : message;
}
