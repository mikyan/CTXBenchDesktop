import { describe, expect, it } from "vitest";
import { createDemoSnapshot } from "../data/demo";
import { renderSnapshotHtml } from "./report";

describe("renderSnapshotHtml", () => {
  it("creates a self-contained report and escapes task text", () => {
    const snapshot = createDemoSnapshot();
    snapshot.runs[0].taskId = "<script>alert(1)</script>";
    const report = renderSnapshotHtml(snapshot);
    expect(report).toContain("<!doctype html>");
    expect(report).toContain("&lt;script&gt;alert(1)&lt;/script&gt;");
    expect(report).not.toContain("<script>alert(1)</script>");
  });
});
