import { describe, expect, it, vi } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createOfflineExportStore, defaultExportImages, receiveExportProgress, validExportImages, type OfflineExport } from "./offline-export";
import { newImageBuild } from "./image-build";
import type { BuildProgressEvent, WorkerActionResult } from "./infrastructure";
import { OfflineImageExport, OfflineExportProgress } from "../components/OfflineImageExport";
import { I18nContext } from "../i18n.context";
import { translate } from "../i18n";

const selections = () => defaultExportImages.map(({ role, reference }) => ({ role, reference }));
const initial = (): OfflineExport => ({ ...newImageBuild("Ubuntu", 1), packagePath: "D:\\离线 包\\custom.zip", images: selections(), exportPhase: "checking", completed: 0, total: 0 });
const event = (lines: string[]): BuildProgressEvent => ({ phase: "building", lines, elapsedMs: 1000, lastOutputMs: 1000 });
const control = (phase: string, completed = 0, total = 0) => "CTXBENCH_EXPORT_PROGRESS " + JSON.stringify({ phase, completed, total });

describe("offline image export", () => {
  it("requires exactly four roles and accepts internal registry tags and local digests, not commands", () => {
    const images = selections();
    expect(validExportImages(images)).toBe(true);
    images[2].reference = "registry.internal:5000/team/pi:company-v1";
    images[3].reference = `sha256:${"a".repeat(64)}`;
    expect(validExportImages(images)).toBe(true);
    expect(validExportImages(images.slice(1))).toBe(false);
    expect(validExportImages([...images.slice(1), images[1]])).toBe(false);
    for (const reference of ["", "--help", "x;touch /tmp/x", "$(id)", "image\nother", "a".repeat(257)]) {
      expect(validExportImages(images.map((image, index) => index === 0 ? { ...image, reference } : image))).toBe(false);
    }
  });

  it("uses bounded logs and accepts an unknown total only during Docker save", () => {
    let state = receiveExportProgress(initial(), event([control("save", 1048576, 0), "Exporting local layers"]));
    expect(state).toMatchObject({ exportPhase: "save", completed: 1048576, total: 0, lines: ["Exporting local layers"] });
    state = receiveExportProgress(state, event([
      control("unknown", 100, 100), control("package", 1, 0), control("save", -1, 0), control("verify", .5, 100),
      control("save", 1, -1), control("verify", 1, Number.MAX_SAFE_INTEGER + 1), "CTXBENCH_EXPORT_PROGRESS invalid", "CTXBENCH_EXPORT_PROGRESS null",
    ]));
    expect(state).toMatchObject({ exportPhase: "save", completed: 1048576, total: 0 });
    state = receiveExportProgress(state, event([control("package", 50, 100), ...Array.from({ length: 2000 }, () => "Saved layer")]));
    expect(state).toMatchObject({ exportPhase: "package", completed: 50, total: 100 });
    expect(state.lines).toHaveLength(500);
    expect(state.omitted).toBeGreaterThan(0);
    const ended = { ...state, status: "failed" as const };
    expect(receiveExportProgress(ended, event([control("complete", 4, 4)]))).toBe(ended);
  });

  it("freezes selections, deduplicates starts, retains progress across navigation and ignores late events", async () => {
    let send!: (value: BuildProgressEvent) => void;
    let finish!: (value: WorkerActionResult) => void;
    const runner = vi.fn((_distro, _path, _images, callback) => { send = callback; return new Promise<WorkerActionResult>((resolve) => { finish = resolve; }); });
    const store = createOfflineExportStore(runner);
    const listener = vi.fn();
    const unsubscribe = store.subscribe(listener);
    const images = selections();
    const pending = store.start("Ubuntu", "D:\\custom.zip", images);
    images[2].reference = "changed:later";
    expect(store.getSnapshot()?.images[2].reference).toBe("ctxbench/agent-pi:0.1.0");
    expect(store.start("Debian", "different.zip", images)).toBe(pending);
    await Promise.resolve();
    expect(runner.mock.calls[0][2][2].reference).toBe("ctxbench/agent-pi:0.1.0");
    send(event([control("save", 10, 0)]));
    unsubscribe(); listener.mockClear();
    send(event([control("package", 50, 100)]));
    expect(listener).not.toHaveBeenCalled();
    expect(store.getSnapshot()?.exportPhase).toBe("package");
    const previousSend = send;
    finish({ ok: false, code: "disk_space", detail: "no space left" }); await pending;
    expect(store.getSnapshot()).toMatchObject({ status: "failed", result: { code: "disk_space" } });
    send(event([control("complete", 4, 4)]));
    expect(store.getSnapshot()?.exportPhase).toBe("package");
    const retry = store.start("Ubuntu", "D:\\new.zip", selections());
    expect(store.getSnapshot()).toMatchObject({ id: 2, lines: [], exportPhase: "checking" });
    previousSend(event([control("save", 1000, 0)]));
    expect(store.getSnapshot()?.exportPhase).toBe("checking");
    await Promise.resolve(); finish({ ok: true, code: "images_export", detail: "verified" }); await retry;
    expect(store.getSnapshot()?.status).toBe("completed");
    expect(runner).toHaveBeenCalledTimes(2);
  });

  it("does not disclose rejected IPC errors and permits retry after a lost connection", async () => {
    const runner = vi.fn().mockRejectedValueOnce(new Error("sensitive transport detail")).mockResolvedValue({ ok: true, code: "images_export", detail: "done" });
    const store = createOfflineExportStore(runner);
    await store.start("Ubuntu", "D:\\custom.zip", selections());
    expect(store.getSnapshot()?.status).toBe("failed");
    expect(store.getSnapshot()?.result?.detail).not.toContain("sensitive");
    await store.start("Ubuntu", "D:\\new.zip", selections());
    expect(store.getSnapshot()?.status).toBe("completed");
  });

  it("renders the export entry and honest per-stage progress in both languages", () => {
    for (const locale of ["en", "zh-CN"] as const) {
      const render = (children: React.ReactNode) => renderToStaticMarkup(createElement(I18nContext.Provider, { value: { locale, setLocale: () => {}, t: (key, values) => translate(locale, key, values) }, children }));
      const setup = render(createElement(OfflineImageExport, { distribution: "Ubuntu", disabled: false, onBegin: () => {} }));
      expect(setup).toContain(translate(locale, "Package customized Docker images"));
      let state = receiveExportProgress(initial(), event([control("save", 2097152, 0)]));
      let markup = render(createElement(OfflineExportProgress, { state }));
      expect(markup.match(/<progress[^>]*>/)?.[0]).not.toContain("value=");
      expect(markup).toContain(translate(locale, "Archive data processed: {size} MiB (total unknown)", { size: "2.0" }));
      state = receiveExportProgress(state, event([control("package", 25, 100)]));
      markup = render(createElement(OfflineExportProgress, { state }));
      expect(markup).toContain('value="0.25"');
      expect(markup).not.toContain(translate(locale, "Custom image ZIP exported"));
      expect(render(createElement(OfflineExportProgress, { state: { ...initial(), status: "failed" } }))).toContain('value="0"');
      expect(render(createElement(OfflineExportProgress, { state: { ...state, status: "completed" } }))).toContain('value="1"');
    }
  });
});
