import { describe, expect, it } from "vitest";
import { translate, type Locale } from "../i18n";
import { benchmarkLabel, CTXBENCH_LABEL, datasetLabel } from "./benchmark-labels";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { I18nProvider } from "../i18n";
import { DatasetDialog } from "../components/WorkbenchDialogs";

const translator = (locale: Locale) => (key: string) => translate(locale, key);

describe("benchmark display names", () => {
  it("renders the import option with its unchanged internal value and new visible name", () => {
    const html = renderToStaticMarkup(createElement(I18nProvider, {
      children: createElement(DatasetDialog, { onClose: () => {}, onComplete: () => {} }),
    }));
    expect(html).toContain('<option value="ctxbench" selected="">CTXBench (formerly AGENTBench)</option>');
    expect(html).toContain('accept=".parquet,.json,.jsonl"');
    expect(html).not.toContain('value="agentbench.parquet"');
    expect(html).not.toContain("CTXBench / AGENTBench");
  });

  it("uses the current name and explains the old name in both languages", () => {
    expect(benchmarkLabel("ctxbench", translator("zh-CN"))).toBe("CTXBench（原 AGENTBench）");
    expect(benchmarkLabel("ctxbench", translator("en"))).toBe(CTXBENCH_LABEL);
    expect(benchmarkLabel("swebench", translator("en"))).toBe("SWE-bench");
    expect(benchmarkLabel("custom", translator("zh-CN"))).toBe("自定义");
  });

  it("displays the existing official dataset under the new name without mutating its record", () => {
    const dataset = Object.freeze({ id: "frozen-id", name: "AGENTBench official 138", benchmark: "ctxbench" as const, count: 138 });
    expect(datasetLabel(dataset, translator("zh-CN"))).toBe("CTXBench（原 AGENTBench）");
    expect(datasetLabel(dataset, translator("en"))).toBe(CTXBENCH_LABEL);
    expect(dataset.name).toBe("AGENTBench official 138");
    expect(dataset.id).toBe("frozen-id");
  });

  it("localizes the default name of newly imported datasets", () => {
    expect(datasetLabel({ name: CTXBENCH_LABEL, benchmark: "ctxbench", count: 138 }, translator("zh-CN")))
      .toBe("CTXBench（原 AGENTBench）");
  });

  it("preserves custom names, source paths and unrelated benchmarks", () => {
    for (const name of ["Team AGENTBench subset", "agentbench.parquet", "eth-sri/agentbench@138", "AGENTBench official 100"]) {
      expect(datasetLabel({ name, benchmark: "ctxbench", count: 138 }, translator("zh-CN"))).toBe(name);
    }
    expect(datasetLabel({ name: "AGENTBench official 138", benchmark: "custom", count: 138 }, translator("zh-CN")))
      .toBe("AGENTBench official 138");
  });
});
