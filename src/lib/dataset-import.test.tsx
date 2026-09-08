import { afterEach, describe, expect, it, vi } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { datasetFileError, maxDatasetBytes, officialSnapshot, previewDatasetFile } from "./dataset-import";
import { datasetImportChinese } from "../i18n.dataset-import";
import { translate } from "../i18n";
import { DatasetFileImport } from "../components/DatasetFileImport";
import { I18nContext } from "../i18n.context";
import standardDatasets from "../data/standard-datasets.json";

afterEach(() => vi.unstubAllGlobals());
describe("local dataset file import", () => {
  it("supports official binary Parquet and rejects empty, oversized or unrelated files", () => {
    for (const name of ["train-00000-of-00001.parquet", "自定义.json", "tasks.JSONL"]) expect(datasetFileError({ name, size: 1024 })).toBeUndefined();
    for (const file of [{ name: "a.parquet", size: 0 }, { name: "a.json", size: maxDatasetBytes + 1 }, { name: "images.zip", size: 1024 }, { name: "setup.exe", size: 1024 }]) expect(datasetFileError(file)).toBeTruthy();
    for (const row of standardDatasets) expect(officialSnapshot(row.sha256)?.id).toBe(row.id);
    expect(officialSnapshot("0".repeat(64))).toBeUndefined();
  });
  it("passes selected bytes to a fixed native command, never a Windows or container path", async () => {
    const invoke = vi.fn().mockResolvedValue({ token: "fixture", count: 138 });
    vi.stubGlobal("window", { __TAURI_INTERNALS__: { invoke } });
    const bytes = Uint8Array.from([80, 65, 82, 49, 0, 255]);
    const file = { name: "中文.parquet", size: bytes.length, arrayBuffer: async () => bytes.buffer } as File;
    await previewDatasetFile(file, "CTXBench", "ctxbench");
    expect(invoke).toHaveBeenCalledWith("preview_dataset_file", { filename: file.name, bytes: Array.from(bytes), name: "CTXBench", benchmark: "ctxbench" }, undefined);
  });
  it("makes initial selection local-only, requires a check before confirmation and translates all feedback", () => {
    for (const [key, value] of Object.entries(datasetImportChinese)) expect(translate("zh-CN", key)).toBe(value);
    for (const locale of ["en", "zh-CN"] as const) {
      const html = renderToStaticMarkup(createElement(I18nContext.Provider, { value: { locale, setLocale: () => {}, t: (key, values) => translate(locale, key, values) }, children: createElement(DatasetFileImport, { initialBenchmark: "ctxbench", onComplete: () => {}, onClose: () => {}, onBusy: () => {} }) }));
      expect(html).toContain('accept=".parquet,.json,.jsonl"');
      expect(html).not.toContain("File in worker datasets directory");
      expect(html).not.toContain("/var/lib/ctxbench");
      expect(html).not.toContain('role="alert"');
      expect(html).toContain(translate(locale, "Check selected file"));
      expect(html).not.toContain(`>${translate(locale, "Confirm dataset import")}</button>`);
    }
  });
});
