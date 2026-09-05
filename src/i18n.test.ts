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
});
