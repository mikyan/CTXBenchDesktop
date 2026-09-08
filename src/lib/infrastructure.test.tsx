/// <reference types="node" />
import { describe, expect, it } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { InfrastructureSetup } from "../components/InfrastructureSetup";
import { I18nContext } from "../i18n.context";
import { translate } from "../i18n";
import { activityState, diagnosticReport, prerequisiteLabels, recoveryActions, recoveryLabels, quoteShell, setupCommands, setupMessage, setupMessages, type DeploymentInfo } from "./infrastructure";
import { RuntimeSafety } from "../components/RuntimeSafety";
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
  it("never treats missing or failed activity checks as an idle Docker daemon", () => {
    for (const value of [undefined, info, { ...info, activeContainers: [], activityError: "Docker unavailable" }]) {
      expect(activityState(value).known).toBe(false);
      expect(activityState(value).canReplace).toBe(false);
    }
    const checked = { ...info, activeContainers: [], activityError: null };
    expect(activityState(checked).canReplace).toBe(true);
    for (const role of ["worker", "agent", "grader"] as const) {
      const state = activityState({ ...checked, activeContainers: [{ id: "abc", name: "container", status: "Up", role }] });
      expect(state.canReplace).toBe(false);
      expect(state.tasks).toHaveLength(role === "worker" ? 0 : 1);
    }
  });
  it("provides a non-destructive recovery route for every failure category", () => {
    for (const action of Object.values(recoveryLabels)) expect(translate("zh-CN", action)).not.toBe(action);
    expect(recoveryActions("worker_running")).toEqual(["check", "runtime"]);
    expect(recoveryActions("worker_health")).toContain("logs");
    expect(recoveryActions("network")).toContain("offline");
    expect(recoveryActions("bundle_version")).toContain("downloads");
    expect(recoveryActions("images_import")).toEqual(["runtime"]);
    expect(recoveryActions("unexpected")).toEqual(["check"]);
    const commands = setupCommands(info, "powershell");
    expect(commands.stop).toMatch(/stop ctxbench-worker$/);
    expect(commands.activity).toContain("io.ctxbench.evaluator");
    expect(commands.activity).not.toContain("ps -a");
    expect(commands.activity).not.toMatch(/prune|docker stop|docker rm|inspect/);
    expect(commands.port).toContain("publish=48173");
  });
  it("shows worker and grader blockers with explicit next steps in both languages", () => {
    for (const locale of ["en", "zh-CN"] as const) {
      const render = (deployment: DeploymentInfo | undefined) => renderToStaticMarkup(createElement(I18nContext.Provider, {
        value: { locale, setLocale: () => {}, t: (key, values) => translate(locale, key, values) },
        children: createElement(RuntimeSafety, { info: deployment, distribution: info.distribution, disabled: false, checking: false, onCheck: () => {}, onStop: () => {} }),
      }));
      expect(render(undefined)).toContain(translate(locale, "Container activity is unknown"));
      expect(render(undefined)).not.toContain(translate(locale, "No active CTXBench containers detected"));
      for (const role of ["worker", "grader"] as const) {
        const html = render({ ...info, activityError: null, activeContainers: [{ id: "123abc", name: "blocker-name", role, status: "Up" }] });
        expect(html).toContain("blocker-name");
        expect(html).toContain(translate(locale, role === "worker" ? "Stop the old worker before replacing images" : "Wait for active tasks before maintenance"));
        expect(html).toContain(translate(locale, "Stop worker…"));
        if (role === "grader") expect(html).toContain(`disabled="">${translate(locale, "Stop worker…")}`);
        expect(html).not.toContain(`>${translate(locale, "Confirm and stop worker")}</button>`);
      }
    }
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
