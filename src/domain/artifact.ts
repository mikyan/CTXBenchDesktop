import type { FrozenModelConfig, KnowledgeCapability } from "./types";

export interface ArtifactIdentity {
  repository: string;
  commit: string;
  capability: KnowledgeCapability;
  skillVersion: string;
  generationPromptHash: string;
  builder: FrozenModelConfig;
}

function canonicalize(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, item]) => [key, canonicalize(item)]),
    );
  }
  return value;
}

export function canonicalArtifactIdentity(identity: ArtifactIdentity): string {
  return JSON.stringify(canonicalize(identity));
}

export async function contextArtifactKey(identity: ArtifactIdentity): Promise<string> {
  const payload = new TextEncoder().encode(canonicalArtifactIdentity(identity));
  const digest = await crypto.subtle.digest("SHA-256", payload);
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}
