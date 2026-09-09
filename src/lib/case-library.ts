import type { BenchmarkKind, DatasetRecord, TaskSummary } from '../domain/types';
import { workerRequest } from './desktop';

export interface LibraryCase {
  id: string; name: string; benchmark: BenchmarkKind; revision: number; taskId: string;
  repository: string; baseCommit: string; prompt: string; image?: string;
  createdAt: string; updatedAt: string; originDataset?: string; modified: boolean;
}
export interface LibraryCaseDetail extends LibraryCase {
  row: Record<string, unknown>; usedBy: { id: string; name: string }[];
}
export interface LibrarySet extends DatasetRecord { caseIds: string[]; revision: number; updatedAt: string; originDataset?: string }
export interface LibraryInventory {
  version: number; sets: LibrarySet[]; cases: LibraryCase[];
  importWarnings?: { datasetId: string; name: string; code: string; message: string }[];
}
export interface LibrarySelection { dataset: DatasetRecord; tasks: TaskSummary[]; revision: string }
export interface DatasetSnapshot {
  id: string; sourceId: string; name: string; sourceRevision: number; contentRevision: string;
  dataset: string; benchmark: BenchmarkKind; createdAt: string;
  members: { caseId: string; revision: number; taskId: string; rowHash: string; modified: boolean }[];
}
export const emptyLibrary: LibraryInventory = { version: 1, sets: [], cases: [] };
export function libraryError(cause: unknown): string {
  const message = cause instanceof Error ? cause.message : String(cause);
  return /(?:^|Error: )Not Found$/i.test(message) ?
    'The editable case library requires matching desktop and evaluation service images. Update the application images and restart the service safely; existing results are preserved.' : message;
}
export async function loadLibrary(): Promise<LibraryInventory> {
  try { return await workerRequest<LibraryInventory>('/library'); }
  catch (error) { throw Error(libraryError(error)); }
}
export function librarySources(library: LibraryInventory): DatasetRecord[] {
  return [...library.sets, ...library.cases.map((item) => ({ ...item, count: 1 }))];
}
export function selectionCases(library: LibraryInventory, collection: LibrarySet): LibraryCase[] {
  const index = new Map(library.cases.map((item) => [item.id, item]));
  return collection.caseIds.flatMap((id) => index.has(id) ? [index.get(id)!] : []);
}
