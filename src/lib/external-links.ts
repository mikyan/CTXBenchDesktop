import { openUrl } from "@tauri-apps/plugin-opener";
import standardDatasets from "../data/standard-datasets.json";

export const externalLinks = {
  releases: "https://github.com/mikyan/CTXBenchDesktop/releases",
  help: "https://github.com/mikyan/CTXBenchDesktop",
  wsl: "https://learn.microsoft.com/zh-cn/windows/wsl/install",
  docker: "https://docs.docker.com/engine/install/ubuntu/",
  ctxbenchDataset: standardDatasets[0].homepage,
  ctxbenchDownload: standardDatasets[0].downloadUrl,
  swebenchDataset: standardDatasets[1].homepage,
  swebenchDownload: standardDatasets[1].downloadUrl,
} as const;

export type ExternalDestination = keyof typeof externalLinks;

export function isDesktopLink(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

export async function openExternalLink(destination: ExternalDestination): Promise<void> {
  if (!Object.hasOwn(externalLinks, destination)) throw new Error("Unsupported external link.");
  await openUrl(externalLinks[destination]);
}
