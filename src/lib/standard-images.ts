import type { CompanyProfileRecord, OperatorJob } from "./intranet";
export interface ImageSelection { taskIds: string[]; profile?: CompanyProfileRecord }

export interface ProjectImage {
  reference: string; taskIds: string[]; installed: boolean; compatible: boolean;
  imageId: string | null; sizeBytes: number | null;
  originals?: string[]; pullAllowed?: boolean;
  remote?: { status: string; checkedAt?: string };
}
export interface StandardImagePlan {
  dataset: string; benchmark: string;
  tasks: { id: string; repository: string; images: string[] }[];
  images: ProjectImage[]; operations: OperatorJob[];
  storage: { freeBytes: number; ready: boolean };
}
export function selectedProjectImages(plan: StandardImagePlan, taskIds: string[]) {
  const selected = new Set(taskIds);
  return plan.images.filter((image) => image.taskIds.some((id) => selected.has(id)));
}
export function imageAvailable(image: ProjectImage, now = Date.now()) {
  if (image.installed) return image.compatible;
  return image.pullAllowed !== false && image.remote?.status === "available" && Boolean(image.remote.checkedAt)
    && now - Date.parse(image.remote.checkedAt!) >= 0 && now - Date.parse(image.remote.checkedAt!) < 15 * 60_000;
}
export function availableImageTasks(plan: StandardImagePlan) {
  return plan.tasks.filter((task) => task.images.length > 0 && task.images.every((ref) => {
    const image = plan.images.find((row) => row.reference === ref);
    return Boolean(image && imageAvailable(image));
  })).map((task) => task.id);
}
export function imageStatus(image: ProjectImage) {
  if (image.installed) return image.compatible ? "Installed (not test-validated)" : "Wrong platform";
  if (image.pullAllowed === false) return "No permitted registry mapping";
  const status = image.remote?.status;
  if (status === 'available') return imageAvailable(image) ? "Registry available (not installed)" : "Registry check expired";
  return ({ 'not-found': 'Image not found in registry', 'auth-required': 'Registry login required',
    unreachable: 'Registry connection failed', 'wrong-platform': 'Wrong platform', unmapped: 'No permitted registry mapping' } as Record<string, string>)[status ?? ''] ?? 'Registry not checked';
}
export function standardImageError(cause: unknown) {
  const message = cause instanceof Error ? cause.message : String(cause);
  return /^(?:Error: )?Not Found$/i.test(message)
    ? "Project image installation requires the matching newer local evaluation service image. Update Application images in Settings first."
    : message;
}
