import { describe, expect, it } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { readFileSync } from "node:fs";
import { I18nContext } from "../i18n.context";
import { translate } from "../i18n";
import { StandardImageInstaller } from "../components/StandardImageInstaller";
import { standardImagesChinese } from "../i18n.standard-images";
import { selectedProjectImages, standardImageError, type StandardImagePlan } from "./standard-images";
import { externalLinks } from "./external-links";

describe("standard project image installation", () => {
  it("selects a deduplicated image set for the selected tasks only", () => {
    const plan = { images: [{ reference: "shared", taskIds: ["a", "b"] }, { reference: "other", taskIds: ["c"] }] } as StandardImagePlan;
    expect(selectedProjectImages(plan, ["a", "b"]).map((row) => row.reference)).toEqual(["shared"]);
    expect(selectedProjectImages(plan, [])).toEqual([]);
  });
  it("explains download scope without exposing Docker commands as required first steps", () => {
    for (const locale of ["en", "zh-CN"] as const) {
      const html = renderToStaticMarkup(createElement(I18nContext.Provider, { value: { locale, setLocale: () => {}, t: (key, values) => translate(locale, key, values) },
        children: createElement(StandardImageInstaller, { dataset: "fixture", name: "Official fixture", onClose: () => {} }) }));
      expect(html).toContain(translate(locale, "Downloads only — no model calls"));
      expect(html).toContain(translate(locale, "Refresh image status"));
      expect(html).not.toContain('type="password"');
    }
  });
  it("translates every install label and guides old service upgrades", () => {
    for (const key of Object.keys(standardImagesChinese)) expect(translate("zh-CN", key)).not.toBe(key);
    expect(standardImageError("Not Found")).toContain("Update Application images");
    expect(standardImageError("Registry unavailable")).toBe("Registry unavailable");
  });
  it("allows native opening of upstream image instructions", () => {
    const permissions = readFileSync(new URL("../../src-tauri/capabilities/default.json", import.meta.url), "utf8");
    for (const key of ["ctxbenchImages", "swebenchImages"] as const) expect(permissions).toContain(externalLinks[key]);
  });
});
