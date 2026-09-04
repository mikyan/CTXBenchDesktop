export const percent = (value: number, digits = 1): string => `${(value * 100).toFixed(digits)}%`;

export const signedPercent = (value: number, digits = 1): string =>
  `${value >= 0 ? "+" : ""}${(value * 100).toFixed(digits)} pp`;

export const money = (value: number): string =>
  new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(value);

export const duration = (seconds?: number): string => {
  if (seconds === undefined) return "—";
  const minutes = Math.floor(seconds / 60);
  const remainder = Math.round(seconds % 60);
  return `${minutes}m ${remainder.toString().padStart(2, "0")}s`;
};

export const relativeTime = (iso?: string): string => {
  if (!iso) return "—";
  const deltaMinutes = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60_000));
  if (deltaMinutes < 1) return "just now";
  if (deltaMinutes < 60) return `${deltaMinutes}m ago`;
  if (deltaMinutes < 1_440) return `${Math.round(deltaMinutes / 60)}h ago`;
  return `${Math.round(deltaMinutes / 1_440)}d ago`;
};

export const bytes = (value: number): string => {
  if (value < 1_024) return `${value} B`;
  if (value < 1_048_576) return `${(value / 1_024).toFixed(1)} KB`;
  return `${(value / 1_048_576).toFixed(1)} MB`;
};

export const titleCase = (value: string): string =>
  value
    .split("-")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
