/** Browser interaction regression. Native calls are mocked: never connects to a Worker, Docker or Provider.
 * Start with `node scripts/maintenance-ui-smoke.mjs`; Playwright must be available (or set NODE_PATH).
 */
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { mkdir } from "node:fs/promises";
import { resolve } from "node:path";
import { createServer } from "vite";

const { chromium } = createRequire(import.meta.url)("playwright");
const server = await createServer({ server: { host: "127.0.0.1", port: 43174, strictPort: true }, logLevel: "error" });
await server.listen();
let browser;
try {
  browser = await chromium.launch({ headless: true, ...(process.env.CTXBENCH_BROWSER_CHANNEL ? { channel: process.env.CTXBENCH_BROWSER_CHANNEL } : {}) });
  for (const locale of ["en", "zh-CN"]) {
    const page = await browser.newPage({ viewport: { width: 1360, height: 1100 } });
    const errors = [];
    page.on("pageerror", (error) => { errors.push(error.message); console.error(error.message); });
    page.on("requestfailed", (request) => console.error("Request failed:", request.url(), request.failure()?.errorText));
    await page.route("**/worker/**", (route) => route.abort());
    await page.addInitScript(() => {
      localStorage.setItem("ctxbench-distribution", "ubuntu-24.04");
      window.testModel = {
        calls: [], importResult: "worker_running", startResult: "worker_health", buildResult: "network",
        info: { distribution: "ubuntu-24.04", composePath: "C:\\Program Files\\CTXBench\\deployment\\docker\\compose.yaml", wslComposePath: "/mnt/c/Program Files/CTXBench/deployment/docker/compose.yaml", dataDirectory: "/var/lib/ctxbench", checks: [{ id: "compose_file", ok: true, detail: "Found" }], containers: [], missingImages: [], activityError: null, activeContainers: [{ id: "abc123", name: "old-ctxbench-worker", status: "Up 1 hour", role: "worker" }] },
      };
      window.__TAURI_INTERNALS__ = {
        transformCallback: () => 1, unregisterCallback: () => {},
        invoke: async (command, args) => {
          const model = window.testModel;
          model.calls.push({ command, action: args?.action, distribution: args?.distribution, filename: args?.filename, byteCount: args?.bytes?.length, path: args?.path });
          if (command === "desktop_connection") return { isolated: false, baseUrl: "http://127.0.0.1:48173/v1" };
          if (command === "list_wsl_distributions") return { defaultDistribution: "ubuntu-24.04", distributions: ["ubuntu-24.04", "Debian"].map((name) => ({ name, state: "Running", version: 2, isDefault: name !== "Debian" })) };
          if (command === "get_deployment_info") return structuredClone({ ...model.info, distribution: args.distribution });
          if (command === "select_offline_bundle") return "D:\\离线镜像\\images.zip";
          if (command === "import_offline_images") return { ok: model.importResult === "images_import", code: model.importResult, detail: "Import diagnostic fixture" };
          if (command === "worker_control") {
            if (args.action === "stop") { model.info.activeContainers = []; return { ok: true, code: "stop", detail: "Stopped fixture worker" }; }
            if (args.action === "logs") return { ok: true, code: "logs", detail: "Redacted fixture container log" };
            const code = args.action === "build" ? model.buildResult : model.startResult;
            return { ok: code === "start", code, detail: "Recovery fixture detail" };
          }
          if (command === "list_local_images") return { images: [], error: null };
          if (command === "preview_dataset_file") {
            if (model.previewError) throw new Error(model.previewError);
            return { token: "dataset-fixture", filename: args.filename, name: args.name, benchmark: args.benchmark, count: 138, bytes: args.bytes.length, sha256: "a5df3bc98d8a9eed9c5c07a9aed63821c86f212c319e9d4b8623b4dfd6fd0832", samples: [{ id: "example-task", repository: "example/repo", baseCommit: "a".repeat(40) }], testsExecuted: false };
          }
          if (command === "worker_request" && args.path?.endsWith("/confirm")) return { id: "saved-dataset", name: "CTXBench", count: 138, benchmark: "ctxbench" };
          if (command === "worker_request" && args.path?.endsWith("/discard")) return { discarded: true };
          // Hidden company/credential panels may read these; no network request is made.
          if (command === "worker_request") throw new Error("Fixture worker unavailable");
          throw new Error(`Unexpected native command: ${command}`);
        },
      };
    });
    await page.route("**/__maintenance_fixture__*", async (route) => {
      if (!route.request().isNavigationRequest()) return route.continue();
      const html = await server.transformIndexHtml("/__maintenance_fixture__", `<!doctype html><html><head><meta charset="UTF-8" /></head><body><main id="root"></main><script type="module">
        import React from 'react';
        import { createRoot } from 'react-dom/client';
        import { InfrastructurePage } from '/src/pages/InfrastructurePage.tsx';
        import { DatasetDialog } from '/src/components/WorkbenchDialogs.tsx';
        import { I18nContext } from '/src/i18n.context.ts';
        import { translate } from '/src/i18n.tsx';
        import '/src/styles.css';
        import '/src/ux.css';
        const locale = new URLSearchParams(location.search).get('locale');
        window.uiT = key => translate(locale, key);
        const content = new URLSearchParams(location.search).get('panel') === 'dataset'
          ? React.createElement(DatasetDialog, { onClose: () => {}, onComplete: () => { window.importCompleted = true; }, onSettings: section => { window.datasetRecoverySection = section; } })
          : React.createElement(InfrastructurePage, { diagnostics: [], diagnosing: false, initialSection: 'images', onDiagnose: () => {} });
        createRoot(document.getElementById('root')).render(React.createElement(I18nContext.Provider, { value: {locale, setLocale: () => {}, t: (key, values) => translate(locale, key, values)} }, content));
      </script></body></html>`);
      await route.fulfill({ contentType: "text/html", body: html });
    });
    await page.goto(`http://127.0.0.1:43174/__maintenance_fixture__?locale=${locale}`);
    await page.waitForFunction(() => Boolean(window.uiT));
    const t = (key) => page.evaluate((key) => window.uiT(key), key);
    const button = async (key) => page.getByRole("button", { name: await t(key), exact: true });
    const click = async (key) => (await button(key)).click();
    const visible = async (key) => page.getByText(await t(key), { exact: true }).first().waitFor({ state: "visible" });
    const countStops = () => page.evaluate(() => window.testModel.calls.filter((call) => call.action === "stop").length);
    const recheck = async () => {
      await page.locator(".runtime-safety").getByRole("button", { name: await t("Recheck status"), exact: true }).click();
      await page.waitForFunction(() => !document.querySelector(".runtime-safety button").disabled);
    };

    await visible("Stop the old worker before replacing images");
    await click("Select offline images ZIP");
    await page.getByRole("checkbox", { name: await t("I trust this package's source and have paused experiments and stopped the worker.") }).check();
    assert(await (await button("Verify and import images")).isDisabled());
    await click("Stop worker…");
    assert(await (await button("Confirm and stop worker")).isDisabled());
    assert.equal(await countStops(), 0);
    await click("Cancel");
    assert.equal(await countStops(), 0);
    await click("Stop worker…");
    await page.getByRole("checkbox", { name: await t("I have paused experiment scheduling and waited for all generation, preparation and evaluation jobs to finish.") }).check();
    await click("Confirm and stop worker");
    await visible("No active CTXBench containers detected");
    assert.equal(await countStops(), 1);
    assert(await (await button("Verify and import images")).isEnabled());
    await click("Verify and import images");
    await visible("Running CTXBench containers block image replacement");
    await recheck();
    await visible("Running CTXBench containers block image replacement"); // Diagnostics preserve the primary failure.
    await page.evaluate(() => { window.testModel.importResult = "images_import"; });
    await click("Verify and import images");
    await visible("Offline images imported");
    await click("Go to runtime controls");
    await click("Start worker");
    await visible("Containers were started, but the worker is not reachable");
    await page.locator(".setup-feedback.error").getByRole("button", { name: await t("Read container logs"), exact: true }).click();
    await page.getByText("Redacted fixture container log", { exact: true }).waitFor();
    await visible("Containers were started, but the worker is not reachable"); // Reading logs must not erase recovery actions.
    await page.evaluate(() => { window.testModel.startResult = "start"; });
    await click("Start worker");
    await click("Configure runtime credentials");
    assert(await page.getByRole("heading", { name: await t("Model credentials"), exact: true }).isVisible());
    await page.getByRole("navigation", { name: await t("Settings sections") }).getByRole("button", { name: await t("Application images"), exact: true }).click();
    await page.getByRole("radio", { name: await t("Internet available / build images") }).check();
    await click("Build images");
    await visible("A network or certificate check failed");
    await click("Switch to offline installation");
    assert(await (await button("Select offline images ZIP")).isVisible());
    for (const role of ["agent", "grader"]) {
      await page.evaluate((role) => { window.testModel.info.activeContainers = [{ id: "task123", name: "active-test-task", role, status: "Up" }]; }, role);
      await recheck();
      await visible("Wait for active tasks before maintenance");
      assert(await (await button("Stop worker…")).isDisabled());
      assert(await (await button("Verify and import images")).isDisabled());
    }
    await page.evaluate(() => { window.testModel.info.activeContainers = []; window.testModel.info.activityError = "Fixture Docker permission denied"; });
    await recheck();
    await visible("Container activity is unknown");
    assert(await (await button("Stop worker…")).isDisabled());
    assert(await (await button("Verify and import images")).isDisabled());
    // Missing prerequisites must have visible guidance even on the image page.
    await page.evaluate(() => { window.testModel.info.checks = [{ id: "compose_file", ok: false, detail: "Missing fixture compose.yaml" }]; });
    await recheck();
    await visible("Deployment file not found");
    await page.evaluate(() => { window.testModel.info.checks = []; window.testModel.info.activityError = null; window.testModel.info.activeContainers = [{ id: "abc123", name: "another-project-ctxbench-worker", role: "worker", status: "Up 2 hours" }]; });
    await recheck();
    await visible("Stop the old worker before replacing images");
    const folder = resolve("artifacts/maintenance-ui");
    await mkdir(folder, { recursive: true });
    await page.screenshot({ path: resolve(folder, `${locale}.png`), fullPage: true });
    await page.setViewportSize({ width: 980, height: 800 });
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), "No page-level horizontal overflow at desktop minimum width");
    // Switching the target clears consent and hides progress/results from the previous distribution.
    await page.getByRole("combobox", { name: await t("Installed WSL distributions") }).selectOption("Debian");
    await visible("Stop the old worker before replacing images");
    assert(!await page.getByRole("checkbox", { name: await t("I trust this package's source and have paused experiments and stopped the worker.") }).isChecked());
    assert.equal(await page.getByText(await t("A network or certificate check failed"), { exact: true }).count(), 0);
    assert.equal(await countStops(), 1);
    assert.deepEqual(errors, []);
    console.log(`${locale}: maintenance confirmations, recovery routes, state retention, unknown/active blockers and responsive layout passed`);
    await page.goto(`http://127.0.0.1:43174/__maintenance_fixture__?panel=dataset&locale=${locale}`);
    await page.waitForFunction(() => Boolean(window.uiT));
    const input = page.getByLabel(await t("Select downloaded dataset file"));
    assert(await (await button("Check selected file")).isDisabled());
    await input.setInputFiles({ name: "images.zip", mimeType: "application/zip", buffer: Buffer.from("not a dataset") });
    await visible("Select a Parquet, JSON or JSONL dataset file; ZIP and EXE files are not datasets.");
    assert(await (await button("Check selected file")).isDisabled());
    await input.setInputFiles({ name: "train-00000-of-00001.parquet", mimeType: "application/octet-stream", buffer: Buffer.from("PAR1test-dataPAR1") });
    await page.evaluate(() => { window.testModel.previewError = "Local file import requires the matching new evaluation service image. Update it in Settings; no manual file copy is needed."; });
    await click("Check selected file");
    await visible("Local file import requires the matching new evaluation service image. Update it in Settings; no manual file copy is needed.");
    await click("Prepare application images");
    assert.equal(await page.evaluate(() => window.datasetRecoverySection), "images");
    await page.evaluate(() => { window.testModel.previewError = undefined; });
    await click("Check selected file");
    await visible("File checked — ready to import");
    await visible("File checksum matches the pinned official snapshot.");
    assert.equal(await page.evaluate(() => window.testModel.calls.filter((call) => call.path?.endsWith("/confirm")).length), 0);
    assert.equal(await page.locator('input[value="/var/lib/ctxbench/datasets"]').count(), 0);
    await page.getByRole("textbox", { name: await t("Dataset name (optional)") }).fill("My imported CTXBench");
    assert.equal(await (await button("Confirm dataset import")).count(), 0); // Changed inputs invalidate the old preview.
    await click("Check selected file");
    await visible("File checked — ready to import");
    await page.setViewportSize({ width: 1360, height: 1000 });
    await page.screenshot({ path: resolve(folder, `dataset-${locale}.png`), fullPage: true });
    await click("Confirm dataset import");
    await visible("Dataset imported successfully");
    assert(await page.evaluate(() => window.importCompleted));
    assert.equal(await page.evaluate(() => window.testModel.calls.filter((call) => call.path?.endsWith("/confirm")).length), 1);
    const transfers = await page.evaluate(() => window.testModel.calls.filter((call) => call.command === "preview_dataset_file"));
    assert(transfers.every((call) => call.filename === "train-00000-of-00001.parquet" && call.byteCount === 17));
    assert.deepEqual(errors, []);
    console.log(`${locale}: local Parquet selection, invalid-file/old-service recovery, preview invalidation and explicit import confirmation passed`);
    await page.close();
  }
} finally {
  await browser?.close();
  await server.close();
}
