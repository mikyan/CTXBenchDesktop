import { describe, expect, it, vi } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { buildTiming, createImageBuildStore, newImageBuild, receiveBuildProgress } from "./image-build";
import type { BuildProgressEvent, WorkerActionResult } from "./infrastructure";
import { ImageBuildProgress } from "../components/ImageBuildProgress";
import { I18nContext } from "../i18n.context";
import { translate } from "../i18n";

const event = (lines: string[], elapsedMs = 1000, lastOutputMs: number | null = elapsedMs): BuildProgressEvent => ({ phase: "building", lines, elapsedMs, lastOutputMs });

describe("Docker build progress", () => {
  it("counts discovered parallel vertices and cache hits without guessing total time", () => {
    let build = newImageBuild("Ubuntu", 1, 0);
    build = receiveBuildProgress(build, event(["#1 [worker 1/5] FROM python:3.12", "#2 [agent 1/8] FROM node:22", "#1 CACHED", "#3 [worker 2/5] RUN pip install package"]), 1000);
    expect(Object.keys(build.steps)).toHaveLength(3);
    expect(build.steps["1"].status).toBe("done");
    expect(build.steps["2"].status).toBe("running");
    expect(build.phase).toBe("installing");
    build = receiveBuildProgress(build, event(["#2 DONE 1.0s", "#3 ERROR: download failed", "#4 [agent 2/8] RUN npm install", "#4 CANCELED"]));
    expect(Object.keys(build.steps)).toHaveLength(4);
    expect(build.steps["3"].status).toBe("failed");
    expect(build.steps["4"].status).toBe("canceled");
  });
  it("parses actual layer byte progress separately and clears it when the vertex ends", () => {
    let build = receiveBuildProgress(newImageBuild("Ubuntu"), event(["#4 [agent 1/8] FROM node:22", "#4 sha256:abcdef 1.2MB / 10.0MB 0.8s done"]));
    expect(build.transfer).toMatchObject({ downloaded: 1_200_000, total: 10_000_000 });
    build = receiveBuildProgress(build, event(["#4 sha256:abcdef 2MiB / 4MiB"]));
    expect(build.transfer).toMatchObject({ downloaded: 2 * 1024 ** 2, total: 4 * 1024 ** 2 });
    build = receiveBuildProgress(build, event(["#4 DONE 1s"]));
    expect(build.transfer).toBeUndefined();
    for (const text of ["0B / 0B", "20MB / 1MB", "1..2MB / 10MB"]) {
      expect(receiveBuildProgress(newImageBuild("Ubuntu"), event([`#4 sha256:abc ${text}`])).transfer).toBeUndefined();
    }
  });
  it("bounds logs and keeps newest failure output even with unrecognized output", () => {
    const build = receiveBuildProgress(newImageBuild("Ubuntu"), event([...Array.from({ length: 2000 }, (_, i) => `install ${i}`), "final error"]));
    expect(build.lines).toHaveLength(500);
    expect(build.omitted).toBe(1501);
    expect(build.lines.at(-1)).toBe("final error");
    expect(Object.keys(build.steps)).toHaveLength(0);
    const huge = receiveBuildProgress(build, event(Array.from({ length: 50 }, () => "x".repeat(24_000))));
    expect(huge.lines.join("").length).toBeLessThanOrEqual(100_000);
  });
  it("heartbeats never reset silence and finished clocks freeze", () => {
    let build = receiveBuildProgress(newImageBuild("Ubuntu", 1, 100), event(["working"], 1000), 1100);
    build = receiveBuildProgress(build, event([], 10_000, 1000), 10_100);
    expect(buildTiming(build, 32_100)).toEqual({ elapsed: 32_000, silent: 31_000 });
    expect(buildTiming({ ...build, endedAt: 32_100 }, 99_100)).toEqual({ elapsed: 32_000, silent: 31_000 });
  });
  it("keeps an unknown-duration bar until Docker exits, then shows success or failure bilingually", () => {
    for (const locale of ["en", "zh-CN"] as const) {
      const render = (build: ReturnType<typeof newImageBuild>) => renderToStaticMarkup(createElement(I18nContext.Provider, {
        value: { locale, setLocale: () => {}, t: (key, values) => translate(locale, key, values) }, children: createElement(ImageBuildProgress, { build }),
      }));
      const build = newImageBuild("Ubuntu", 1, Date.now());
      expect(render(build)).toContain(translate(locale, "Waiting for Docker output…"));
      expect(render(build).match(/<progress[^>]*>/)?.[0]).not.toContain("value=");
      const doneSteps = receiveBuildProgress(build, event(["#1 CACHED"]));
      expect(render(doneSteps).match(/<progress[^>]*>/)?.[0]).not.toContain("value=");
      expect(render({ ...doneSteps, status: "completed" })).toContain('max="1" value="1"');
      expect(render({ ...doneSteps, status: "failed" })).toContain(translate(locale, "Image build failed"));
      expect(render({ ...build, startedAt: Date.now() - 40_000, eventAt: Date.now() - 40_000 })).toContain(translate(locale, "Live build log (redacted)"));
    }
  });
});

describe("build session lifecycle", () => {
  it("streams before completion, survives unsubscribe/remount and deduplicates build clicks", async () => {
    let onProgress!: (event: BuildProgressEvent) => void;
    let finish!: (result: WorkerActionResult) => void;
    const runner = vi.fn((_action, _distribution, callback) => { onProgress = callback!; return new Promise<WorkerActionResult>((resolve) => { finish = resolve; }); });
    const store = createImageBuildStore(runner);
    const listener = vi.fn();
    const unsubscribe = store.subscribe(listener);
    const first = store.start("Ubuntu");
    expect(store.start("Debian")).toBe(first);
    await Promise.resolve();
    onProgress(event(["#1 RUN install"]));
    expect(store.getSnapshot()?.status).toBe("running");
    expect(store.getSnapshot()?.lines).toContain("#1 RUN install");
    unsubscribe();
    onProgress(event(["#1 DONE"]));
    const remounted = vi.fn();
    store.subscribe(remounted);
    expect(store.getSnapshot()?.steps["1"].status).toBe("done");
    finish({ ok: true, code: "build", detail: "done" });
    await first;
    expect(remounted).toHaveBeenCalled();
    expect(store.getSnapshot()?.status).toBe("completed");
    expect(runner).toHaveBeenCalledTimes(1);
    onProgress(event(["late event"]));
    expect(store.getSnapshot()?.lines).not.toContain("late event");
  });
  it("retains failure logs, resets retries, and hides unclassified IPC exception text", async () => {
    const runner = vi.fn(async (_action, _distribution, onProgress) => {
      onProgress!(event(["failed download"]));
      return { ok: false, code: "network", detail: "certificate error" };
    });
    const store = createImageBuildStore(runner);
    await store.start("Ubuntu");
    expect(store.getSnapshot()).toMatchObject({ status: "failed", lines: ["failed download"], result: { code: "network" } });
    const retry = store.start("Ubuntu");
    expect(store.getSnapshot()).toMatchObject({ id: 2, status: "running", lines: [], steps: {} });
    await retry;
    const broken = createImageBuildStore(async () => { throw new Error("unredacted transport diagnostic"); });
    await broken.start("Ubuntu");
    expect(broken.getSnapshot()?.result?.detail).not.toContain("unredacted");
    expect(broken.getSnapshot()?.result?.detail).toContain("background work may still be running");
  });
});
