import { afterEach, describe, expect, it, vi } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { chooseDistribution, savedDistribution, saveDistribution, type WslInventory } from "./wsl";
import { controlWorker, diagnoseEnvironment, listWslDistributions } from "./desktop";
import { WslDistributionPicker } from "../components/WslDistributionPicker";
import { I18nContext } from "../i18n.context";
import { translate } from "../i18n";
import { wslChinese } from "../i18n.wsl";
import { invoke } from "@tauri-apps/api/core";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn() }));
const inventory: WslInventory = {
  distributions: [{ name: "Ubuntu-24.04", state: "Stopped", version: 2, isDefault: true }, { name: "Debian", state: "Running", version: 1, isDefault: false }],
  defaultDistribution: "Ubuntu-24.04",
};
afterEach(() => { vi.unstubAllGlobals(); vi.clearAllMocks(); });

describe("WSL distribution selection", () => {
  it("uses the native default instead of a hardcoded Ubuntu name", () => {
    expect(chooseDistribution("", inventory)).toBe("Ubuntu-24.04");
    expect(chooseDistribution("  ", inventory)).toBe("Ubuntu-24.04");
    expect(chooseDistribution("", { distributions: [], defaultDistribution: null })).toBe("");
  });
  it("keeps explicit choices, normalizes matching names, and never redirects a missing runtime", () => {
    expect(chooseDistribution(" ubuntu-24.04 ", inventory)).toBe("Ubuntu-24.04");
    expect(chooseDistribution("Debian", inventory)).toBe("Debian");
    expect(chooseDistribution("Company-WSL", inventory)).toBe("Company-WSL");
  });
  it("persists names trimmed and tolerates restricted storage", () => {
    const setItem = vi.fn();
    vi.stubGlobal("localStorage", { getItem: () => " ubuntu-24.04 ", setItem });
    expect(savedDistribution()).toBe("ubuntu-24.04");
    saveDistribution(" Ubuntu-24.04 ");
    expect(setItem).toHaveBeenCalledWith("ctxbench-distribution", "Ubuntu-24.04");
    vi.stubGlobal("localStorage", { getItem: () => { throw new Error("Blocked"); }, setItem: () => { throw new Error("Blocked"); } });
    expect(savedDistribution()).toBe("");
    expect(() => saveDistribution("Debian")).not.toThrow();
  });
  it("enumerates through the desktop without requiring a running worker", async () => {
    vi.stubGlobal("window", { __TAURI_INTERNALS__: {} });
    vi.mocked(invoke).mockResolvedValue(inventory);
    expect(await listWslDistributions()).toEqual(inventory);
    expect(invoke).toHaveBeenCalledExactlyOnceWith("list_wsl_distributions");
  });
  it("never invents installed distributions in browser previews", async () => {
    vi.stubGlobal("window", {});
    await expect(listWslDistributions()).rejects.toThrow("requires the desktop");
    expect(invoke).not.toHaveBeenCalled();
  });
  it("lets native diagnostics choose a default and forwards explicit names trimmed", async () => {
    vi.stubGlobal("window", { __TAURI_INTERNALS__: {} });
    await diagnoseEnvironment("");
    expect(invoke).toHaveBeenLastCalledWith("diagnose_environment", { distribution: null });
    await diagnoseEnvironment(" ubuntu-24.04 ");
    expect(invoke).toHaveBeenLastCalledWith("diagnose_environment", { distribution: "ubuntu-24.04" });
    await controlWorker("build", " Ubuntu-24.04 ");
    expect(invoke).toHaveBeenLastCalledWith("worker_control", { action: "build", distribution: "Ubuntu-24.04" });
    vi.mocked(invoke).mockClear();
    await expect(controlWorker("start", "  ")).rejects.toThrow("Select an installed");
    expect(invoke).not.toHaveBeenCalled();
  });
  it("renders selection, refresh and manual input in Chinese and English", () => {
    for (const locale of ["en", "zh-CN"] as const) {
      const html = renderToStaticMarkup(createElement(I18nContext.Provider, {
        value: { locale, t: (key, values) => translate(locale, key, values), setLocale: () => {} },
        children: createElement(WslDistributionPicker, { value: "Ubuntu-24.04", onChange: () => {} }),
      }));
      expect(html).toContain(translate(locale, "Installed WSL distributions"));
      expect(html).toContain(translate(locale, "Refresh distributions"));
      expect(html).toContain(translate(locale, "Distribution name (editable)"));
      expect(html).toContain('value="Ubuntu-24.04"');
      expect(html).toContain("<select");
    }
    for (const [key, value] of Object.entries(wslChinese)) expect(translate("zh-CN", key)).toBe(value);
    expect(translate("zh-CN", "Distribution {distribution} is not in the installed WSL list.", { distribution: "Company-WSL" })).toContain("Company-WSL");
  });
});
