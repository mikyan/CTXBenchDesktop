import { describe, expect, it } from "vitest";
import { createElement, type ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { ConfirmDialog, Modal } from "../components/Dialogs";
import { TestImagePicker } from "../components/TestImagePicker";
import { I18nContext } from "../i18n.context";
import { translate } from "../i18n";
import { dialogsChinese } from "../i18n.dialogs";
import { bundledImageRole, imageRoleHints } from "./test-images";
import { testTemplates } from "./dataset-authoring";

const render = (children: ReactNode, locale: "en" | "zh-CN" = "en") => renderToStaticMarkup(createElement(I18nContext.Provider, { value: { locale, setLocale: () => {}, t: (key, values) => translate(locale, key, values) }, children }));
describe("confirmation and test image guidance", () => {
  it("uses a named modal alertdialog and puts initial focus on the safe action", () => {
    const html = render(createElement(ConfirmDialog, { title: "Discard?", description: "Unsaved changes", confirmLabel: "Discard", onCancel: () => {}, onConfirm: () => {}, disabled: true }));
    expect(html).toContain('role="alertdialog"');
    expect(html).toContain('aria-modal="true"');
    expect(html).toContain('aria-describedby=');
    expect(html).toMatch(/autofocus=""[^>]*>Cancel/);
    expect(html).toMatch(/class="button danger" disabled="">Discard/);
  });
  it("shows why closing is unavailable instead of silently ignoring it", () => {
    const html = render(createElement(Modal, { title: "Processing", busy: true, onClose: () => {}, children: "Form" }));
    expect(html).toContain('aria-busy="true"');
    expect(html).toContain("Working — please wait before closing.");
    expect(html).toMatch(/aria-label="Close" disabled=""/);
  });
  it("only classifies known bundled names, never claims arbitrary company images are compatible", () => {
    expect(bundledImageRole("ctxbench/agent-pi:0.1.0")).toBe("agent");
    expect(bundledImageRole("ctxbench/official-harness@sha256:abc")).toBe("harness");
    expect(bundledImageRole("ctxbench/worker:0.1.0")).toBe("worker");
    expect(bundledImageRole("ctxbench/egress-proxy:0.1.0")).toBe("proxy");
    expect(bundledImageRole("registry.company:5000/team/agent-pi:test")).toBeUndefined();
    expect(bundledImageRole("sha256:abc")).toBeUndefined();
    expect(bundledImageRole("constructor")).toBeUndefined();
    expect(bundledImageRole("__proto__")).toBeUndefined();
    expect(testTemplates.unittest).toMatch(/^python3 /);
    expect(testTemplates.pytest).toMatch(/^python3 /);
  });
  it("offers selection, manual entry and an honest explanation of all four roles in both languages", () => {
    for (const locale of ["en", "zh-CN"] as const) {
      const html = render(createElement(TestImagePicker, { value: "ctxbench/agent-pi:0.1.0", onChange: () => {} }), locale);
      for (const key of ["Choose an installed image", "Test image reference", "Can I use the four imported application images?", ...Object.values(imageRoleHints)]) expect(html).toContain(translate(locale, key));
      expect(html).toContain("/opt/venv");
      expect(html).toContain("python3 -m unittest");
    }
    for (const [key, value] of Object.entries(dialogsChinese)) expect(translate("zh-CN", key)).toBe(value);
  });
});
