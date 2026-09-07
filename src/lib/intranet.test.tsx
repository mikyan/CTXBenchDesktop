import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { companyProfileSchema, defaultCompanyProfile, namesFromLines, terminalOperatorJob, buildFiles } from "./intranet";
import { IntranetWorkbench } from "../components/IntranetWorkbench";
import { DatasetSelfTest } from "../components/DatasetSelfTest";
import { DatasetDrafts } from "../components/DatasetDrafts";
import { OperatorJobPanel } from "../components/OperatorJobPanel";
import { newDatasetDraft, draftFromManifest, datasetRows, draftDifference } from "./dataset-authoring";
import { I18nContext } from "../i18n.context";
import { translate } from "../i18n";
import { intranetChinese } from "../i18n.intranet";

function render(element: React.ReactNode, locale: "en" | "zh-CN" = "en") {
  return renderToStaticMarkup(createElement(I18nContext.Provider, { value: { locale, setLocale: () => {}, t: (key, values) => translate(locale, key, values) } }, element));
}
describe("intranet operator tools", () => {
  it("profiles are strict, share names not environment values, and default to offline preparation", () => {
    const profile = defaultCompanyProfile();
    expect(companyProfileSchema.parse(profile)).toEqual(profile);
    expect(profile.offline).toBe(true);
    expect(companyProfileSchema.safeParse({ ...profile, apiKey: "secret" }).success).toBe(false);
    expect(namesFromLines("TEAM_KEY\nTEAM_URL, TEAM_KEY")).toEqual(["TEAM_KEY", "TEAM_URL"]);
  });
  it("copies evaluator manifests without losing commands, patches or custom metadata", () => {
    const rows = [{ id: "one", repository: "https://git.company.example/a", baseCommit: "a".repeat(40), prompt: "Repair this behavior", image: "team/tests:v1", test: { command: ["python", "-m", "unittest"], hiddenPatch: "private hidden patch" }, goldPatch: "private reference", metadata: { team: "example" } }];
    const draft = draftFromManifest("Copied", rows);
    expect(datasetRows(draft)).toEqual(rows);
    const edited = { ...draft, tasks: [{ ...draft.tasks[0], prompt: "New requirement" }] };
    expect(draftDifference(draft, edited)).toEqual({ added: 0, removed: 0, changed: 1, defaultsChanged: false });
    expect(draft.tasks[0].prompt).toBe(rows[0].prompt);
  });
  it("rejects oversized or duplicate build uploads", async () => {
    await expect(buildFiles([{ name: "a", size: 32 * 1024 * 1024 } as File])).rejects.toThrow("30 MiB");
    await expect(buildFiles([{ name: "a", size: 0 } as File, { name: "a", size: 0 } as File])).rejects.toThrow("unique");
  });
  it("has bilingual first-class workbench and explicit self-test consent", () => {
    for (const locale of ["en", "zh-CN"] as const) {
      const html = render(createElement(IntranetWorkbench), locale);
      expect(html).toContain(translate(locale, "Company deployment workbench"));
      for (const tab of ["Company profiles", "Image adaptation", "Dataset self-test", "Portable resources"]) expect(html).toContain(translate(locale, tab));
      const probe = render(createElement(DatasetSelfTest, { payload: "{}" }), locale);
      expect(probe).toContain(translate(locale, "Run self-test (no model tokens)"));
      expect(probe).toContain("disabled");
    }
  });
  it("draft restoration explicitly warns that evaluator data is private and current draft will be replaced", () => {
    const html = render(createElement(DatasetDrafts, { draft: newDatasetDraft(), onLoad: () => {}, disabled: false }));
    expect(html).toContain("not browser storage");
    expect(html).toContain("Loading replaces");
  });
  it("never labels a container exit pattern as proven test quality", () => {
    const html = render(createElement(OperatorJobPanel, { initial: { id: "op-1", kind: "intranet:probe", status: "completed", result: { reports: [{ taskId: "a", candidateReady: true, phases: {} }] } } }));
    expect(html).toContain("review required");
    expect(html).toContain("not proof");
    expect(terminalOperatorJob("running")).toBe(false);
    expect(terminalOperatorJob("failed")).toBe(true);
  });
  it("keeps all intranet translations active without conflicting legacy labels", () => {
    for (const [key, value] of Object.entries(intranetChinese)) expect(translate("zh-CN", key)).toBe(value);
  });
});
