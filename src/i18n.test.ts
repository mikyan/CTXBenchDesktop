import { describe, expect, it } from "vitest";
import { normalizeLocale, translate } from "./i18n";

describe("i18n", () => {
  it("normalizes Chinese browser locales", () => {
    expect(normalizeLocale("zh-CN")).toBe("zh-CN");
    expect(normalizeLocale("zh-TW")).toBe("zh-CN");
    expect(normalizeLocale("en-US")).toBe("en");
  });

  it("translates and interpolates Chinese messages", () => {
    expect(translate("zh-CN", "{count} graded runs", { count: 4 })).toBe("4 次已评分运行");
  });

  it("uses source English as a safe fallback", () => {
    expect(translate("en", "Unregistered copy")).toBe("Unregistered copy");
    expect(translate("zh-CN", "Unregistered copy")).toBe("Unregistered copy");
  });

  it("localizes the multi-variable controls and validation", () => {
    expect(translate("zh-CN", "Add variable")).toBe("添加变量");
    expect(translate("zh-CN", "Save environment variables")).toBe("保存全部环境变量");
    expect(translate("zh-CN", "Remove variable {index}", { index: 2 })).toBe("移除变量 2");
    expect(translate("zh-CN", "Each environment variable name must be unique.")).toBe("环境变量名称不能重复。");
    expect(translate("en", "Save environment variables")).toBe("Save environment variables");
  });
});
