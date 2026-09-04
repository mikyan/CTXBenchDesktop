import type { DashboardSnapshot } from "./types";

function escapeHtml(value: unknown): string {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

export function renderSnapshotHtml(snapshot: DashboardSnapshot): string {
  const metrics = snapshot.metrics;
  const cards = [
    ["Graded runs", metrics.totalRuns],
    ["Pass rate", `${(metrics.passRate * 100).toFixed(1)}%`],
    ["Knowledge lift", `${metrics.knowledgeLift >= 0 ? "+" : ""}${(metrics.knowledgeLift * 100).toFixed(1)} pp`],
    ["PPVR", `${(metrics.passPatchViolationRate * 100).toFixed(1)}%`],
  ];
  const rows = snapshot.runs.map((run) => `<tr>
    <td>${escapeHtml(run.taskId)}</td><td>${escapeHtml(run.arm)}</td>
    <td>${run.testsPassed == null ? "—" : run.testsPassed ? "PASS" : "FAIL"}</td>
    <td>${escapeHtml(run.constraintVerdict ?? "—")}</td><td>${escapeHtml(run.durationSeconds ?? "—")}</td>
  </tr>`).join("");
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
  <title>CTXBench report</title><style>
  :root{color-scheme:dark;font:14px Inter,system-ui,sans-serif;background:#080d13;color:#dce8f2}body{max-width:1100px;margin:48px auto;padding:0 28px}h1{font-size:32px;margin-bottom:6px}p{color:#8294a6}.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:28px 0}.card{padding:18px;border:1px solid #21303d;border-radius:12px;background:#101820}.card span{display:block;color:#8294a6}.card strong{display:block;font-size:24px;margin-top:10px}table{width:100%;border-collapse:collapse;background:#101820;border:1px solid #21303d}th,td{text-align:left;padding:12px;border-bottom:1px solid #21303d}th{color:#8294a6}footer{margin-top:24px;color:#657789}@media(max-width:700px){.cards{grid-template-columns:1fr 1fr}}
  </style></head><body><h1>CTXBench benchmark report</h1><p>Frozen snapshot · ${escapeHtml(new Date().toISOString())}</p>
  <section class="cards">${cards.map(([label, value]) => `<div class="card"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`).join("")}</section>
  <h2>Run outcomes</h2><table><thead><tr><th>Task</th><th>Arm</th><th>Tests</th><th>Constraint</th><th>Seconds</th></tr></thead><tbody>${rows}</tbody></table>
  <footer>Generated locally by CTXBench Desktop. Provider credentials and trajectories are excluded.</footer></body></html>`;
}
