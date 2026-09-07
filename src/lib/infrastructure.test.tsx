/// <reference types="node" />
import { describe, expect, it } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { InfrastructureSetup } from "../components/InfrastructureSetup";
import { I18nContext } from "../i18n.context";
import { translate } from "../i18n";
import { diagnosticReport, prerequisiteLabels, quoteShell, setupCommands, setupMessage, setupMessages, type DeploymentInfo } from "./infrastructure";
import { infrastructureChinese } from "../i18n.infrastructure";
import { readFileSync } from "node:fs";
const css = readFileSync(new URL("../styles.css", import.meta.url), "utf8");

const info: DeploymentInfo = {
  distribution: "Ubuntu-24.04", composePath: "C:\\Program Files\\CTXBench Desktop\\deployment\\docker\\compose.yaml",
  wslComposePath: "/mnt/c/Program Files/CTXBench Desktop/deployment/docker/compose.yaml", dataDirectory: "/var/lib/ctxbench",
  missingImages: [], containers: [], checks: [{ id: "compose_file", ok: true, detail: "Found" }],
};

describe("deployment guidance", () => {
  it("uses absolute, quoted paths and never implicitly builds or pulls on start", () => {
    for (const shell of ["wsl", "powershell"] as const) {
      const commands = setupCommands(info, shell);
      expect(commands.start).toContain("--no-build --pull never");
      expect(commands.start).toContain(`'${info.wslComposePath}'`);
      expect(commands.start).not.toContain("--build ");
      expect(commands.build).toContain("--profile build-only build");
      expect(commands.directory).toContain("sudo mkdir -p -- '/var/lib/ctxbench'");
    }
    expect(setupCommands(info, "powershell").start).toContain("wsl.exe --distribution 'Ubuntu-24.04' --exec");
    expect(setupCommands({ ...info, wslComposePath: null }, "wsl")).toEqual({});
    expect(quoteShell("user's data", "wsl")).toBe("'user'\"'\"'s data'");
    expect(quoteShell("user's data", "powershell")).toBe("'user''s data'");
  });
  it("has specific next steps and complete translations for every native error category", () => {
    for (const { title, help } of Object.values(setupMessages)) {
      expect(translate("zh-CN", title)).not.toBe(title);
      expect(translate("zh-CN", help)).not.toBe(help);
    }
    for (const label of Object.values(prerequisiteLabels)) {
      if (label !== "Docker Engine") expect(translate("zh-CN", label)).not.toBe(label);
    }
    for (const [key, value] of Object.entries(infrastructureChinese)) expect(translate("zh-CN", key)).toBe(value);
    expect(setupMessage("unexpected")).toEqual(setupMessages.action);
    expect(setupMessage("images").help).toContain("does not include Docker images");
    expect(setupMessage("worker_health").help).toContain("localhost");
  });
  it("renders offline-first instructions and never offers a broken relative-path command", () => {
    for (const locale of ["en", "zh-CN"] as const) {
      const html = renderToStaticMarkup(createElement(I18nContext.Provider, {
        value: { locale, setLocale: () => {}, t: (key, values) => translate(locale, key, values) },
        children: createElement(InfrastructureSetup, { distribution: "Ubuntu-24.04", onDistribution: () => {}, onDiagnose: () => {}, onBusy: () => {}, diagnosing: false }),
      }));
      expect(html).toContain(translate(locale, "Offline installation"));
      expect(html).toContain(translate(locale, "Read container logs"));
      expect(html).toContain(translate(locale, "Select offline images ZIP"));
      expect(html).toContain("ctxbench-images-manifest.json");
      expect(html).not.toContain("ctxbench-images.py verify .");
      expect(html).not.toContain("docker compose -f docker/compose.yaml");
      expect(html).not.toContain(`>${translate(locale, "Build images")}</button>`);
    }
  });
  it("copies only the deliberately limited diagnostic shape", () => {
    const report = diagnosticReport(info, { ok: false, code: "images", detail: "No such image: ctxbench/worker:0.1.0" });
    expect(report).toContain("Ubuntu-24.04");
    expect(report).toContain("images (FAILED)");
    expect(report).not.toContain("environment");
  });
});

function luminance(hex: string): number {
  const rgb = hex.slice(1).match(/../g)!.map((part) => parseInt(part, 16) / 255).map((part) => part <= .04045 ? part / 12.92 : ((part + .055) / 1.055) ** 2.4);
  return .2126 * rgb[0] + .7152 * rgb[1] + .0722 * rgb[2];
}
describe("desktop readability guardrails", () => {
  it("has no tiny type declarations, including shorthand monospace fonts", () => {
    const sizes = [...css.matchAll(/(?:font-size:\s*|font:\s*[^;{}]*?)(\d+)px/g)];
    expect(sizes.length).toBeGreaterThan(50);
    for (const match of sizes) {
      expect(Number(match[1]), match[0]).toBeGreaterThanOrEqual(12);
    }
  });
  it("keeps primary and secondary tokens above 4.5:1 on all standard dark surfaces", () => {
    for (const token of ["text", "muted", "dim", "cyan", "green", "red", "orange", "violet"]) {
      const foreground = css.match(new RegExp(`--${token}:\\s*(#[0-9a-f]{6})`))![1];
      for (const background of ["#080d13", "#101923", "#151f2b", "#10212b"]) {
        expect((luminance(foreground) + .05) / (luminance(background) + .05), `${token} on ${background}`).toBeGreaterThanOrEqual(4.5);
      }
    }
  });
  it("retains wrapping, scrolling and reduced-motion accommodations", () => {
    expect(css).toContain("overflow-wrap:anywhere");
    expect(css).toContain(".compact-table-wrap, .constraints-table-panel { overflow-x:auto;");
    expect(css).toContain("prefers-reduced-motion: reduce");
    expect(css).not.toContain(".experiment-actions{display:none}");
    expect(css).toContain('"Cascadia Mono", Consolas, "Liberation Mono", monospace');
    expect(css).not.toContain('"DM Mono"');
    expect(css).toContain("display:inline-flex; white-space:nowrap; margin-top:0");
  });
});
