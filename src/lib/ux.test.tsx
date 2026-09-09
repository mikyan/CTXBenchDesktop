import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { I18nContext } from "../i18n.context";
import { translate } from "../i18n";
import { uxChinese } from "../i18n.ux";
import { settingsSections } from "./navigation";
import { companyFeatureError } from "./intranet";
import { SectionNav } from "../components/SectionNav";
import { Sidebar } from "../components/Sidebar";
import { InfrastructurePage } from "../pages/InfrastructurePage";
import { ExperimentsPage } from "../pages/ExperimentsPage";
import { DashboardPage } from "../pages/DashboardPage";
import { DatasetsPage } from "../pages/DatasetsPage";
import { ExperimentComposer } from "../components/ExperimentComposer";
import { PreparationDialog, RunDialog } from "../components/WorkbenchDialogs";
import { createDemoSnapshot } from "../data/demo";

const noop = () => {};
function render(element: React.ReactNode, locale: "en" | "zh-CN" = "en") {
  return renderToStaticMarkup(createElement(I18nContext.Provider, { value: { locale, setLocale: noop, t: (key, values) => translate(locale, key, values) } }, element));
}
describe("task-oriented UX", () => {
  it("keeps every new Chinese label active", () => {
    for (const [key, value] of Object.entries(uxChinese)) expect(translate("zh-CN", key), key).toBe(value);
  });
  it("has one Settings entry, first-class datasets and a current-page marker", () => {
    const html = render(<Sidebar page="datasets" onNavigate={noop} />);
    expect(html.match(/>Settings</g)).toHaveLength(1);
    expect(html).not.toContain(">Infrastructure<");
    expect(html).toContain('aria-current="page"');
    expect(html).toContain(">Datasets<");
  });
  it("uses ordinary keyboard-accessible buttons, not incomplete ARIA tabs", () => {
    const html = render(<SectionNav label="Settings sections" items={settingsSections} value="runtime" onChange={noop} vertical />);
    expect(html.match(/<button/g)).toHaveLength(6);
    expect(html.match(/aria-current="page"/g)).toHaveLength(1);
    expect(html).not.toContain('role="tab"');
    expect(html).toContain("Company customization");
  });
  it.each(settingsSections.map((item) => item.id))("renders the %s category with a single primary heading", (section) => {
    const html = render(<InfrastructurePage initialSection={section} diagnostics={[]} onDiagnose={noop} diagnosing={false} />);
    expect(html.match(/<h1/g)).toHaveLength(1);
    expect(html).toContain("settings-layout");
    expect(html.match(/ hidden=""/g)?.length).toBeGreaterThanOrEqual(3);
  });
  it("starts experiment creation with task selection, keeping other step state mounted", () => {
    const html = render(<ExperimentComposer creating={false} onClose={noop} onCreate={async () => {}} artifacts={[]} />);
    expect(html).toContain('hidden="" class="composer-step"');
    expect(html).toContain("Continue to execution");
    expect(html).not.toContain(">Create &amp; prepare</button>");
    expect(html).toContain("Advanced workflows");
  });
  it("separates plans, result evidence and budgets, with a CTX-specific entry", () => {
    const html = render(<ExperimentsPage snapshot={createDemoSnapshot()} initialBenchmark="ctxbench" onDatasets={noop} onNewExperiment={noop} onRun={noop} onAction={noop} onExport={noop} />);
    expect(html).toContain("Results &amp; evidence");
    expect(html).toContain("Benchmark filter");
    expect(html).toContain('value="ctxbench" selected=""');
    expect(html).toContain("exports include the entire workspace");
  });
  it("does not advertise mock or incomplete results as real CTX coverage", () => {
    const snapshot = createDemoSnapshot();
    snapshot.experiments = snapshot.experiments.slice(0, 1).map((experiment) => ({ ...experiment, benchmark: "ctxbench" }));
    const run = { ...snapshot.runs[0], experimentId: snapshot.experiments[0].id, mock: false, status: "completed" as const, testsPassed: true };
    snapshot.runs = [run, { ...run, id: "mock", mock: true }, { ...run, id: "incomplete", status: "grading" }, { ...run, id: "unknown", testsPassed: undefined }];
    const html = render(<DashboardPage snapshot={snapshot} onRun={noop} onNewExperiment={noop} onOpenExperiments={noop} />);
    const coverage = html.split('class="coverage-grid"')[1].split('</section>')[0];
    expect(coverage).toContain("<strong>1</strong>");
    expect(coverage.match(/<strong>0<\/strong>/g)).toHaveLength(2);
    expect(html).toContain("not full-suite certification");
  });
  it("shows preparation as active work even before solver runs start", () => {
    const snapshot = createDemoSnapshot();
    snapshot.experiments = [{ ...snapshot.experiments[0], name: "Preparing frozen contexts", status: "preparing", totalRuns: 0, completedRuns: 0 }];
    const html = render(<DashboardPage snapshot={snapshot} onRun={noop} onNewExperiment={noop} onOpenExperiments={noop} />);
    expect(html).toContain("Preparing frozen contexts");
    expect(html).not.toContain("No active experiment");
    expect(html).not.toContain("NaN");
  });
  it("provides creation guidance while waiting for the independent case library", () => {
    const snapshot = { ...createDemoSnapshot(), datasets: [] };
    const html = render(<DatasetsPage snapshot={snapshot} onImport={noop} onCreate={noop} onExperiment={noop} />);
    expect(html).not.toContain("No datasets yet");
    expect(html).toContain("Loading…");
    expect(html).toContain("Create cases independently. Compose datasets from existing cases.");
    expect(html).toContain("Compose dataset");
  });
  it("never mixes a paused experiment's stale run into the active experiment card", () => {
    const snapshot = createDemoSnapshot();
    snapshot.experiments = [{ ...snapshot.experiments[0], id: "active", status: "running" }];
    snapshot.runs = [
      { ...snapshot.runs[0], id: "old", experimentId: "paused", taskId: "stale-paused-task", status: "grading" },
      { ...snapshot.runs[0], id: "current", experimentId: "active", taskId: "current-ctx-task", status: "running" },
    ];
    const html = render(<DashboardPage snapshot={snapshot} onRun={noop} onNewExperiment={noop} onOpenExperiments={noop} />);
    const card = html.split('class="panel active-panel"')[1].split('class="panel results-panel"')[0];
    expect(card).toContain("current-ctx-task");
    expect(card).not.toContain("stale-paused-task");
  });
  it("shows verdicts before expandable raw metadata and keeps one-based repeat labels", () => {
    const run = { ...createDemoSnapshot().runs[0], repeat: 2, arm: "skill-generated" as const, status: "completed" as const, testsPassed: undefined };
    const html = render(<RunDialog run={run} onClose={noop} />);
    expect(html).toContain("<dd>Skill Generated · 2</dd>");
    expect(html).toContain("<dd>Not graded</dd>");
    expect(html).toContain("<details><summary>Frozen metadata and hashes</summary>");
    expect(html.indexOf('class="review-grid"')).toBeLessThan(html.indexOf("Frozen metadata"));
    expect(html).toContain("Evidence file");
  });
  it("keeps optional generation workflow and Agent arguments inside disclosures", () => {
    const html = render(<PreparationDialog kind="context" onClose={noop} onComplete={noop} />);
    expect(html).toContain('<details class="advanced-form"><summary>Advanced workflows</summary>');
    expect(html).toContain('<details class="advanced-form"><summary>Runtime and budgets</summary>');
  });
  it("explains old-worker feature errors without masking unrelated failures", () => {
    expect(companyFeatureError(new Error("Not Found"))).toContain("newer Worker image");
    expect(companyFeatureError("Worker unavailable")).toBe("Worker unavailable");
  });
  it("keeps hidden controls out of flex layouts and readable density at small desktop widths", () => {
    const css = readFileSync(new URL("../ux.css", import.meta.url), "utf8");
    expect(css).toContain("[hidden] { display:none !important; }");
    expect(css).toContain("@media(max-width:1100px)");
    expect(css).toContain("focus-visible");
    for (const size of css.matchAll(/font-size:\s*(\d+)px/g)) expect(Number(size[1])).toBeGreaterThanOrEqual(12);
  });
});
