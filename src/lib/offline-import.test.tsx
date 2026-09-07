import { describe, expect, it, vi } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createOfflineImportStore, receiveImportProgress, type OfflineImport } from "./offline-import";
import { newImageBuild } from "./image-build";
import type { BuildProgressEvent, WorkerActionResult } from "./infrastructure";
import { OfflineImageImport, OfflineImportProgress } from "../components/OfflineImageImport";
import { I18nContext } from "../i18n.context";
import { translate } from "../i18n";

const initial = (): OfflineImport => ({ ...newImageBuild("Ubuntu", 1), packagePath: "D:\\离线 包\\images.zip", importPhase: "checking", completed: 0, total: 0 });
const event = (lines: string[]): BuildProgressEvent => ({ phase: "building", lines, elapsedMs: 1000, lastOutputMs: 1000 });
const control = (phase: string, completed = 0, total = 0) => "CTXBENCH_IMPORT_PROGRESS " + JSON.stringify({ phase, completed, total });
describe("offline import", () => {
  it("separates validated stage controls from bounded logs and rejects invalid progress", () => {
    let state = receiveImportProgress(initial(), event([control("verify", 50, 100), "Verifying package"]));
    expect(state).toMatchObject({ importPhase: "verify", completed: 50, total: 100, lines: ["Verifying package"] });
    state = receiveImportProgress(state, event([control("unknown", 100, 100), control("load", 200, 100), control("load", -1, 100), control("load", .5, 100), "CTXBENCH_IMPORT_PROGRESS invalid"]));
    expect(state.importPhase).toBe("verify");
    state = receiveImportProgress(state, event([control("load", 100, 100), control("unpack")]));
    expect(state).toMatchObject({ status: "running", importPhase: "unpack", total: 0 });
    state = receiveImportProgress(state, event(Array.from({ length: 2000 }, () => "loaded image")));
    expect(state.lines).toHaveLength(500);
  });
  it("retains in-flight imports across navigation, deduplicates clicks and preserves failures", async () => {
    let send!: (value: BuildProgressEvent) => void;
    let finish!: (value: WorkerActionResult) => void;
    const runner = vi.fn((_distro, _path, callback) => { send = callback; return new Promise<WorkerActionResult>((resolve) => { finish = resolve; }); });
    const store = createOfflineImportStore(runner);
    const unsubscribe = store.subscribe(vi.fn());
    const pending = store.start("Ubuntu", "D:\\images.zip");
    expect(store.start("Debian", "different.zip")).toBe(pending);
    await Promise.resolve();
    send(event([control("verify", 10, 100)]));
    unsubscribe();
    send(event([control("load", 50, 100)]));
    expect(store.getSnapshot()?.importPhase).toBe("load");
    finish({ ok: false, code: "bundle_invalid", detail: "bad checksum" });
    await pending;
    expect(store.getSnapshot()?.status).toBe("failed");
    send(event([control("complete", 4, 4)]));
    expect(store.getSnapshot()?.importPhase).toBe("load");
    expect(runner).toHaveBeenCalledTimes(1);
    const retry = store.start("Ubuntu", "D:\\new.zip");
    expect(store.getSnapshot()).toMatchObject({ id: 2, lines: [], importPhase: "checking" });
    await Promise.resolve(); finish({ ok: true, code: "images_import", detail: "done" }); await retry;
    expect(store.getSnapshot()?.status).toBe("completed");
  });
  it("shows single-download instructions, explicit trust confirmation and honest phase bars in both languages", () => {
    for (const locale of ["en", "zh-CN"] as const) {
      const render = (children: React.ReactNode) => renderToStaticMarkup(createElement(I18nContext.Provider, { value: { locale, setLocale: () => {}, t: (key, values) => translate(locale, key, values) }, children }));
      const setup = render(createElement(OfflineImageImport, { distribution: "Ubuntu", disabled: false, onBegin: () => {} }));
      expect(setup).toContain(translate(locale, "Download one images ZIP"));
      expect(setup).toContain("ctxbench-images-manifest.json");
      expect(setup).not.toContain("sha256sum --check");
      expect(setup).toContain('class="button primary" disabled=""');
      let state = receiveImportProgress(initial(), event([control("load", 50, 100)]));
      expect(render(createElement(OfflineImportProgress, { state }))).toContain('value="0.5"');
      state = receiveImportProgress(state, event([control("unpack")]));
      expect(render(createElement(OfflineImportProgress, { state })).match(/<progress[^>]*>/)?.[0]).not.toContain("value=");
      expect(render(createElement(OfflineImportProgress, { state: { ...state, status: "failed" } }))).toContain('value="0"');
      expect(render(createElement(OfflineImportProgress, { state: { ...state, status: "completed" } }))).toContain('value="1"');
    }
  });
});
