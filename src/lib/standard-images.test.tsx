import { describe, expect, it } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { readFileSync } from "node:fs";
import { I18nContext } from "../i18n.context";
import { translate } from "../i18n";
import { StandardImageInstaller } from "../components/StandardImageInstaller";
import { standardImagesChinese } from "../i18n.standard-images";
import { availableImageTasks, imageAvailable, imageStatus, normalizeProjectImageAddress, selectedProjectImages, standardImageError, type ProjectImage, type StandardImagePlan } from "./standard-images";
import { externalLinks } from "./external-links";

describe("standard project image installation", () => {
  it('accepts full internal paths and extracts only a single literal docker pull address', () => {
    const target = 'harbor.company.example:5000/mirror/planbenchx86:Internal-v1';
    expect(normalizeProjectImageAddress(' docker pull ' + target + '\n')).toBe(target);
    expect(normalizeProjectImageAddress(target)).toBe(target);
    expect(normalizeProjectImageAddress('')).toBe('');
    expect(normalizeProjectImageAddress('harbor.company.example/image@sha256:' + 'a'.repeat(64))).toContain('@sha256:');
    for (const value of ['docker pull --all-tags ' + target, target + '; id', target + ' && true',
      'https://' + target, 'user:password@' + target, '${REGISTRY}/image', 'namespace/image:v1', target + ' | tee /tmp/log'])
      expect(() => normalizeProjectImageAddress(value), value).toThrow();
  });
  it("never selects unknown, missing, private, unreachable or stale remote images as available", () => {
    const image: ProjectImage = { reference: 'registry.example/project:v1', taskIds: ['one'], installed: false, compatible: true, imageId: null, sizeBytes: null, pullAllowed: true };
    for (const status of ['unchecked', 'not-found', 'auth-required', 'unreachable', 'local', 'wrong-platform']) {
      expect(imageAvailable({ ...image, remote: { status, checkedAt: new Date().toISOString() } })).toBe(false);
    }
    const available = { ...image, remote: { status: 'available', checkedAt: new Date().toISOString() } };
    expect(imageAvailable(available)).toBe(true);
    expect(imageAvailable({ ...available, pullAllowed: false })).toBe(false);
    expect(imageAvailable({ ...image, remote: { status: 'available', checkedAt: new Date(Date.now() - 16 * 60_000).toISOString() } })).toBe(false);
    expect(imageAvailable({ ...image, installed: true })).toBe(true);
    expect(imageAvailable({ ...image, installed: true, compatible: false })).toBe(false);
    expect(imageStatus({ ...image, remote: { status: 'auth-required' } })).toBe('Registry login required');
    const plan = { tasks: [{ id: 'one', images: [image.reference] }, { id: 'two', images: ['missing'] }], images: [available] } as StandardImagePlan;
    expect(availableImageTasks(plan)).toEqual(['one']);
    expect(plan.tasks).toHaveLength(2);
  });
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
