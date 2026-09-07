import { afterEach, describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { ExternalLink } from "../components/ExternalLink";
import { I18nContext } from "../i18n.context";
import { translate } from "../i18n";
import { externalLinks, isDesktopLink, openExternalLink, type ExternalDestination } from "./external-links";

afterEach(() => vi.unstubAllGlobals());

describe("external links in the desktop shell", () => {
  it("calls the native default-browser opener with the exact release URL", async () => {
    const invoke = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("window", { __TAURI_INTERNALS__: { invoke } });
    expect(isDesktopLink()).toBe(true);
    await openExternalLink("releases");
    expect(invoke).toHaveBeenCalledExactlyOnceWith("plugin:opener|open_url", { url: externalLinks.releases, with: undefined }, undefined);
  });
  it("does not discard native launch errors and rejects arbitrary destinations", async () => {
    const invoke = vi.fn().mockRejectedValue(new Error("OS denied browser launch"));
    vi.stubGlobal("window", { __TAURI_INTERNALS__: { invoke } });
    await expect(openExternalLink("help")).rejects.toThrow("OS denied browser launch");
    invoke.mockClear();
    for (const value of ["file:///C:/private", "javascript:alert(1)", "https://untrusted.invalid", "toString"]) {
      await expect(openExternalLink(value as ExternalDestination)).rejects.toThrow("Unsupported external link");
    }
    expect(invoke).not.toHaveBeenCalled();
  });
  it("keeps browser preview as a normal accessible new-tab link in both languages", () => {
    vi.stubGlobal("window", {});
    expect(isDesktopLink()).toBe(false);
    for (const locale of ["en", "zh-CN"] as const) {
      const html = renderToStaticMarkup(createElement(I18nContext.Provider, {
        value: { locale, setLocale: () => {}, t: (key, values) => translate(locale, key, values) },
        children: createElement(ExternalLink, { destination: "releases", children: translate(locale, "Open release downloads") }),
      }));
      expect(html).toContain(`href="${externalLinks.releases}"`);
      expect(html).toContain('target="_blank"');
      expect(html).toContain('rel="noopener noreferrer"');
      expect(html).toContain(translate(locale, "Open release downloads"));
    }
  });
  it("matches the native allowlist without enabling arbitrary URLs, files or shells", () => {
    const capability = JSON.parse(readFileSync(new URL("../../src-tauri/capabilities/default.json", import.meta.url), "utf8"));
    expect(capability.windows).toEqual(["main"]);
    const opener = capability.permissions.filter((item: unknown) => typeof item === "object");
    expect(opener).toEqual([{ identifier: "opener:allow-open-url", allow: Object.values(externalLinks).map((url) => ({ url })) }]);
    expect(capability.permissions.filter((item: unknown) => typeof item === "string")).toEqual(["core:default"]);
    const native = readFileSync(new URL("../../src-tauri/src/lib.rs", import.meta.url), "utf8");
    expect(native).toContain("tauri_plugin_opener::Builder::new().open_js_links_on_click(false).build()");
  });
  it("localizes launch and clipboard failure guidance", () => {
    for (const key of ["Could not open the default browser. Copy this address and open it manually.", "Copy link", "Link copied.", "Could not copy. Select the address and copy it manually."]) {
      expect(translate("zh-CN", key)).not.toBe(key);
      expect(translate("en", key)).toBe(key);
    }
  });
});
