import type { DashboardSnapshot } from "./types";
import { aggregateDashboard, pairedComparisons } from "./metrics";

function escapeHtml(value: unknown): string {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

export function renderSnapshotHtml(snapshot: DashboardSnapshot): string {
  const realRuns = snapshot.runs.filter((run) => !run.mock);
  const metrics = aggregateDashboard(realRuns);
  const comparisons = pairedComparisons(realRuns);
  const cards = [
    ["Graded runs", metrics.totalRuns],
    ["Pass rate", metrics.totalRuns ? `${(metrics.passRate * 100).toFixed(1)}%` : "N/A"],
    ["Infrastructure failures", metrics.failedRuns ?? 0],
    ["PPVR", metrics.passingApplicable ? `${(metrics.passPatchViolationRate * 100).toFixed(1)}% (${metrics.passingApplicable} applicable passing runs)` : "N/A"],
  ];
  const rows = snapshot.runs.map((run) => `<tr>
    <td>${escapeHtml(run.experimentId)}<br>${escapeHtml(run.taskId)}</td><td>${escapeHtml(run.arm)}${run.mock ? " [MOCK]" : ""}</td>
    <td>${run.testsPassed == null ? "—" : run.testsPassed ? "PASS" : "FAIL"}</td>
    <td>${escapeHtml(run.constraintVerdict ?? "—")}</td><td>${escapeHtml(run.durationSeconds ?? "—")}</td><td>${escapeHtml(run.status)} ${escapeHtml(run.failure ?? "")}</td>
  </tr>`).join("");
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
  <title>CTXBench report</title><style>
  :root{color-scheme:dark;font:14px Inter,system-ui,sans-serif;background:#080d13;color:#dce8f2}body{max-width:1100px;margin:48px auto;padding:0 28px}h1{font-size:32px;margin-bottom:6px}p{color:#8294a6}.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:28px 0}.card{padding:18px;border:1px solid #21303d;border-radius:12px;background:#101820}.card span{display:block;color:#8294a6}.card strong{display:block;font-size:24px;margin-top:10px}table{width:100%;border-collapse:collapse;background:#101820;border:1px solid #21303d}th,td{text-align:left;padding:12px;border-bottom:1px solid #21303d}th{color:#8294a6}footer{margin-top:24px;color:#657789}@media(max-width:700px){.cards{grid-template-columns:1fr 1fr}}
  </style></head><body><h1>CTXBench benchmark report</h1><p>Frozen snapshot · ${escapeHtml(new Date().toISOString())}</p>
  <section class="cards">${cards.map(([label, value]) => `<div class="card"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`).join("")}</section>
  <p>Only real runs with a functional grade enter test metrics. Missing grades are not failures; missing judge results are not neutral votes. A failed later judge does not erase an already-completed functional grade. Mock rows remain explicitly labelled below.</p>
  <h2>Paired comparisons by experiment</h2><p>Lift is averaged across independent tasks; 95% interval uses task-cluster bootstrap (2,000 draws, seed 42). Repeated runs are not independent tasks. One-task experiments cannot estimate population uncertainty.</p>
  ${snapshot.experiments.filter((item) => item.deletedResultGroups).map((item) => `<p>${escapeHtml(item.name)}: ${escapeHtml(item.deletedResultGroups)} comparison groups were deleted. Statistics use only remaining results; this is not the original full cohort.</p>`).join('')}
  <table><thead><tr><th>Experiment / model</th><th>Arm</th><th>Tasks / pairs</th><th>Lift (pp)</th><th>95% CI (pp)</th><th>Repeat variance</th></tr></thead><tbody>${comparisons.map((item) => { const experiment = snapshot.experiments.find((experiment) => experiment.id === item.experimentId); return `<tr><td>${escapeHtml(experiment?.name ?? item.experimentId)}<br>${escapeHtml(experiment?.model.model)}</td><td>${escapeHtml(item.arm)}</td><td>${item.taskCount} / ${item.pairs}</td><td>${(item.lift * 100).toFixed(1)}</td><td>${item.ci95 ? item.ci95.map((value) => (value * 100).toFixed(1)).join(" … ") : "N/A — more tasks required"}</td><td>${item.repeatVariance.toFixed(4)}</td></tr>`; }).join("")}</tbody></table>
  <h2>Run outcomes</h2><table><thead><tr><th>Experiment / task</th><th>Arm</th><th>Tests</th><th>Constraint</th><th>Seconds</th><th>Status</th></tr></thead><tbody>${rows}</tbody></table>
  <h2>Frozen configurations</h2>${snapshot.experiments.map((experiment) => `<details><summary>${escapeHtml(experiment.name)}</summary><pre>${escapeHtml(JSON.stringify(experiment, null, 2))}</pre></details>`).join("")}
  <footer>Generated locally by CTXBench Desktop. Provider credentials and trajectories are excluded.</footer></body></html>`;
}
