import { describe, expect, it } from "vitest";
import { createDemoSnapshot } from "../data/demo";
import { renderSnapshotHtml } from "./report";

describe("renderSnapshotHtml", () => {
  it('discloses deleted comparison groups even when no runs remain', () => {
    const snapshot = createDemoSnapshot();
    snapshot.runs = [];
    snapshot.experiments[0].name = '<deleted-cohort>';
    snapshot.experiments[0].deletedResultGroups = 2;
    const report = renderSnapshotHtml(snapshot);
    expect(report).toContain('&lt;deleted-cohort&gt;: 2 comparison groups were deleted');
    expect(report).not.toContain('<deleted-cohort>');
    expect(report).toContain('not the original full cohort');
  });
  it("creates a self-contained report and escapes task text", () => {
    const snapshot = createDemoSnapshot();
    snapshot.runs[0].taskId = "<script>alert(1)</script>";
    const report = renderSnapshotHtml(snapshot);
    expect(report).toContain("<!doctype html>");
    expect(report).toContain("&lt;script&gt;alert(1)&lt;/script&gt;");
    expect(report).not.toContain("<script>alert(1)</script>");
  });
});
