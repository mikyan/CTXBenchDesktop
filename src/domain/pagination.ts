export function pageWindow(total: number, requested: number, size = 50) {
  if (!Number.isInteger(size) || size < 1) throw new Error("Page size must be a positive integer");
  const pages = Math.max(1, Math.ceil(Math.max(0, total) / size));
  const page = Math.max(0, Math.min(pages - 1, Math.floor(requested)));
  return { page, pages, start: page * size, end: Math.min(total, (page + 1) * size) };
}
