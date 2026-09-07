import { afterEach, describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import standardDatasets from "../data/standard-datasets.json";
import { StandardDatasetDownloads } from "../components/StandardDatasetDownloads";
import { DatasetDialog } from "../components/WorkbenchDialogs";
import { I18nContext } from "../i18n.context";
import { I18nProvider, translate } from "../i18n";
import { openExternalLink, externalLinks } from "./external-links";

afterEach(() => vi.unstubAllGlobals());

describe("standard dataset download guidance", () => {
  it("pins the exact official snapshots with separate splits, filenames, counts and checksums", () => {
    expect(standardDatasets.map(({ id, tasks, split }) => ({ id, tasks, split }))).toEqual([
      { id: "ctxbench", tasks: 138, split: "train" }, { id: "swebench", tasks: 500, split: "test" },
    ]);
    expect(new Set(standardDatasets.map(item => item.filename)).size).toBe(2);
    const guide = readFileSync(new URL("../../docs/standard-datasets.md", import.meta.url), "utf8");
    for (const item of standardDatasets) {
      expect(item.revision).toMatch(/^[a-f0-9]{40}$/);
      expect(item.sha256).toMatch(/^[a-f0-9]{64}$/);
      const url = new URL(item.downloadUrl);
      expect(url.origin).toBe("https://huggingface.co");
      expect(url.pathname).toBe(`/datasets/${item.repository}/resolve/${item.revision}/data/${item.filename}`);
      expect(url.searchParams.get("download")).toBe("true");
      for (const value of [item.downloadUrl, item.homepage, item.sha256, item.revision, item.workerFilename]) expect(guide).toContain(value);
    }
  });

  it("renders both official downloads, offline prerequisites and source selection in both languages", () => {
    for (const locale of ["en", "zh-CN"] as const) {
      const html = renderToStaticMarkup(createElement(I18nContext.Provider, {
        value: { locale, setLocale: () => {}, t: (key, values) => translate(locale, key, values) },
        children: createElement(StandardDatasetDownloads, { benchmark: "swebench", onSelect: () => {} }),
      }));
      for (const dataset of standardDatasets) {
        expect(html).toContain(dataset.downloadUrl.replaceAll("&", "&amp;"));
        expect(html).toContain(dataset.sha256);
        expect(html).toContain(dataset.filename);
      }
      expect(html).toContain(translate(locale, "How to import the downloaded file offline"));
      expect(html).toContain(translate(locale, "Unavailable until the Worker is connected"));
      expect(html.match(/aria-pressed="true"/g)).toHaveLength(1);
      expect(html).toContain(translate(locale, "Dataset files include evaluator-only reference patches and test material. Never provide the full dataset to the coding agent or knowledge builder. Baseline repositories, task images and prepared grading images still need separate preparation."));
    }
  });

  it("uses the exact native browser opener links for dataset pages and downloads", async () => {
    const invoke = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("window", { __TAURI_INTERNALS__: { invoke } });
    for (const key of ["ctxbenchDataset", "ctxbenchDownload", "swebenchDataset", "swebenchDownload"] as const) {
      await openExternalLink(key);
      expect(invoke).toHaveBeenLastCalledWith("plugin:opener|open_url", { url: externalLinks[key], with: undefined }, undefined);
    }
  });

  it("keeps standard sources visible for custom imports and disables selection during import", () => {
    const html = renderToStaticMarkup(createElement(I18nProvider, { children: createElement(StandardDatasetDownloads, { benchmark: "custom", onSelect: () => {}, disabled: true }) }));
    expect(html.match(/disabled=""/g)).toHaveLength(2);
    expect(html).not.toContain('aria-pressed="true"');
    const dialog = renderToStaticMarkup(createElement(I18nProvider, { children: createElement(DatasetDialog, { onClose: () => {}, onComplete: () => {} }) }));
    expect(dialog).toContain("Download standard datasets");
    expect(dialog).toContain('accept=".json,.jsonl"');
  });

  it("provides Chinese translations for new download and import feedback", () => {
    for (const key of ["Download standard datasets", "Official dataset page", "Download pinned Parquet", "Snapshot and checksum", "Use this dataset source", "Reading dataset file…", "Could not read the selected dataset file."]) {
      expect(translate("zh-CN", key)).not.toBe(key);
      expect(translate("en", key)).toBe(key);
    }
  });
});
