export interface WslDistribution {
  name: string;
  state: string;
  version: 1 | 2;
  isDefault: boolean;
}

export interface WslInventory {
  distributions: WslDistribution[];
  defaultDistribution: string | null;
}

const storageKey = "ctxbench-distribution";

export function savedDistribution(): string {
  try { return localStorage.getItem(storageKey)?.trim() ?? ""; }
  catch { return ""; }
}

export function saveDistribution(name: string): void {
  try { localStorage.setItem(storageKey, name.trim()); }
  catch { /* A restricted WebView must still allow selection for this session. */ }
}

export function chooseDistribution(current: string, inventory: WslInventory): string {
  const name = current.trim();
  if (name) return inventory.distributions.find((item) => item.name.toLowerCase() === name.toLowerCase())?.name ?? name;
  return inventory.defaultDistribution ?? "";
}
