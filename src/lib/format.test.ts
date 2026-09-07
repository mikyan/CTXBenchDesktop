import { describe, expect, it } from "vitest";
import { percent, signedPercent } from "./format";

describe("signedPercent", () => {
  it("spells out percentage points in Chinese for negative, positive and zero lift", () => {
    expect(signedPercent(-0.019, 1, "zh-CN")).toBe("-1.9 个百分点");
    expect(signedPercent(0.019, 1, "zh-CN")).toBe("+1.9 个百分点");
    expect(signedPercent(0, 1, "zh-CN")).toBe("+0.0 个百分点");
  });

  it("keeps the English unit and existing precision argument", () => {
    expect(signedPercent(-0.019)).toBe("-1.9 pp");
    expect(signedPercent(0.019, 1, "en")).toBe("+1.9 pp");
    expect(signedPercent(0.01234, 2)).toBe("+1.23 pp");
    expect(signedPercent(0.01234, 2, "zh-CN")).toBe("+1.23 个百分点");
  });

  it("localizes confidence interval bounds without changing ordinary percentages", () => {
    expect([-0.019, 0.025].map((value) => signedPercent(value, 1, "zh-CN")).join(" … "))
      .toBe("-1.9 个百分点 … +2.5 个百分点");
    expect(percent(0.481)).toBe("48.1%");
  });
});
