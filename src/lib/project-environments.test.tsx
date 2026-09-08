import { beforeEach, describe, expect, it, vi } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { ProjectEnvironmentField, requireProjectEnvironment } from "../components/ProjectEnvironmentField";
import { I18nContext } from "../i18n.context";
import { translate } from "../i18n";
import { projectEnvironmentChinese } from "../i18n.project-environments";
import { workerRequest } from "./desktop";

vi.mock("./desktop", () => ({ workerRequest: vi.fn() }));
beforeEach(() => vi.clearAllMocks());
describe("project build environments", () => {
  it("explains dependency preparation and advanced mode in both languages", () => {
    for (const locale of ["en", "zh-CN"] as const) {
      const render = (value: boolean) => renderToStaticMarkup(createElement(I18nContext.Provider, {
        value: { locale, setLocale: () => {}, t: (key, values) => translate(locale, key, values) },
        children: createElement(ProjectEnvironmentField, { value, onChange: () => {} }),
      }));
      expect(render(true)).toContain('checked=""');
      expect(render(false)).not.toContain('checked=""');
      expect(render(true)).toContain(translate(locale, "Agent build environment"));
      expect(render(false)).toContain(locale === "en" ? "Advanced as-is mode" : "高级模式");
      expect(render(true)).toContain(locale === "en" ? "hidden tests" : "隐藏测试");
    }
    for (const [key, value] of Object.entries(projectEnvironmentChinese)) expect(translate("zh-CN", key)).toBe(value);
  });
  it("blocks old services instead of silently ignoring the new flag", async () => {
    vi.mocked(workerRequest).mockResolvedValue({});
    await expect(requireProjectEnvironment(true, key => translate("zh-CN", key))).rejects.toThrow("更新镜像");
    expect(workerRequest).toHaveBeenCalledExactlyOnceWith("/runtime");
  });
  it("only reads capabilities; as-is mode needs no update or mutation", async () => {
    await requireProjectEnvironment(false, key => key);
    expect(workerRequest).not.toHaveBeenCalled();
    vi.mocked(workerRequest).mockResolvedValue({ projectEnvironmentVersion: 1 });
    await expect(requireProjectEnvironment(true, key => key)).resolves.toBeUndefined();
    expect(workerRequest).toHaveBeenCalledExactlyOnceWith("/runtime");
  });
});
