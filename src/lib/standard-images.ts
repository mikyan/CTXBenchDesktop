import type { OperatorJob } from "./intranet";

export interface ProjectImage {
  reference: string; taskIds: string[]; installed: boolean; compatible: boolean;
  imageId: string | null; sizeBytes: number | null;
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
export function standardImageError(cause: unknown) {
  const message = cause instanceof Error ? cause.message : String(cause);
  return /^(?:Error: )?Not Found$/i.test(message)
    ? "Project image installation requires the matching newer local evaluation service image. Update Application images in Settings first."
    : message;
}
