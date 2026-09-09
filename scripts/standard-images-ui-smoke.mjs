/** Isolated bilingual interaction test; does not pull images or touch real datasets. */
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { mkdir } from "node:fs/promises";
import { resolve } from "node:path";
import { createServer } from "vite";
const { chromium } = createRequire(import.meta.url)("playwright");
const server = await createServer({ server: { host: "127.0.0.1", port: 43176, strictPort: true }, logLevel: "error" });
await server.listen();
let browser;
try {
  browser = await chromium.launch({ headless: true, channel: process.env.CTXBENCH_BROWSER_CHANNEL || undefined });
  for (const locale of ["en", "zh-CN"]) {
    const page = await browser.newPage({ viewport: { width: 1200, height: 800 } });
    const errors = []; page.on("pageerror", (error) => errors.push(error.message));
    await page.addInitScript(() => {
      window.fixture = { requests: [], job: null, oldService: false, checked: false, installed: false, sourceRevision: 0, addresses: {}, conflict: false };
      const companyProfile = { id: 'company-v1', createdAt: '2026-09-08', document: { format: 'ctxbench-company-profile', version: 1, name: 'Company fixture', provider: 'private', model: 'fixture', agentImage: 'ctxbench/agent-pi:0.1.0', harnessImage: 'ctxbench/official-harness:0.1.0', envNames: [], agentArgs: [], offline: false, gitMirrors: [], providerDomains: [], imageMappings: [{ source: 'upstream/', target: 'registry.example/company/' }] } };
      window.__TAURI_INTERNALS__ = { invoke: async (command, args) => {
        if (command !== "worker_request") throw Error(`Unexpected native command ${command}`);
        window.fixture.requests.push(args);
        if (window.fixture.oldService) throw Error("Not Found");
        if (args.path === '/intranet/profiles') return [companyProfile];
        if (args.path === '/datasets/fixture/project-image-sources' && args.method === 'PUT') {
          if (window.fixture.conflict || args.body.expectedRevision !== window.fixture.sourceRevision) throw Error('Image addresses changed elsewhere. Refresh image status before saving or installing.');
          for (const row of args.body.overrides) { if (row.target) window.fixture.addresses[row.source] = row.target; else delete window.fixture.addresses[row.source]; }
          window.fixture.sourceRevision++;
          return { revision: window.fixture.sourceRevision };
        }
        if (args.path.includes("/project-images")) {
          const company = args.path.includes('profileId=company-v1');
          const prefix = company ? 'registry.example/company/' : 'upstream/';
          const ref = (name) => window.fixture.addresses['upstream/' + name] || prefix + name;
          return {
          imageSources: { revision: window.fixture.sourceRevision, profileId: company ? 'company-v1' : '', overrides: Object.entries(window.fixture.addresses).map(([source, target]) => ({ source, target })) },
          dataset: "fixture", datasetRevision: 'fixture-v1', benchmark: "ctxbench", storage: { freeBytes: 50 * 1024 ** 3, ready: true },
          tasks: ["task-one", "task-two", "task-three"].map((id, i) => ({ id, repository: "https://git.example/org/project", images: [ref(i < 2 ? 'shared:v1' : 'other:v1')] })),
          images: [{ reference: ref('shared:v1'), originals: ['upstream/shared:v1'], taskIds: ['task-one', 'task-two'], installed: company && window.fixture.installed, compatible: true, pullAllowed: true, remote: { status: window.fixture.checked ? 'available' : 'unchecked', checkedAt: new Date().toISOString() } }, { reference: ref('other:v1'), originals: ['upstream/other:v1'], taskIds: ['task-three'], installed: !company, compatible: true, pullAllowed: true, remote: { status: window.fixture.checked ? 'not-found' : 'unchecked', checkedAt: new Date().toISOString() } }],
          operations: window.fixture.job && Boolean(window.fixture.job.company) === company ? [window.fixture.job] : [],
        }; }
        if (args.path === '/intranet/operations/image-check') { window.fixture.checked = true; return window.fixture.job = { id: 'check-1', kind: 'intranet:image-check', status: 'completed', company: true }; }
        if (args.path === '/intranet/operations/check-1') return window.fixture.job;
        if (args.path === "/intranet/operations/standard-images") return window.fixture.job = { id: "install-1", kind: "intranet:standard-images", status: "queued" };
        if (args.path === "/operations/install-1/cancel") return window.fixture.job = { ...window.fixture.job, status: "cancelled" };
        if (args.path === "/operations/install-1/retry") return window.fixture.job = { ...window.fixture.job, status: "running", failure: undefined };
        if (args.path === "/intranet/operations/install-1") return window.fixture.job;
        throw Error(`Unexpected path ${args.path}`);
      } };
    });
    await page.route("**/__standard_images__*", async (route) => {
      if (!route.request().isNavigationRequest()) return route.continue();
      const html = await server.transformIndexHtml("/__standard_images__", `<!doctype html><html><head><meta charset="UTF-8" /></head><body><div id="root"></div><script type="module">
        import React, {useState} from 'react'; import {createRoot} from 'react-dom/client';
        import {StandardImageInstaller} from '/src/components/StandardImageInstaller.tsx';
        import {I18nContext} from '/src/i18n.context.ts'; import {translate} from '/src/i18n.tsx';
        import '/src/styles.css'; import '/src/ux.css';
        const locale = new URLSearchParams(location.search).get('locale'); window.uiT = (key) => translate(locale,key);
        function Fixture() { const [open,setOpen] = useState(true); return open ? React.createElement(StandardImageInstaller,{dataset:'fixture',name:'CTXBench',onClose:()=>setOpen(false),onExperiment:(selection)=>{window.fixture.selection=selection;setOpen(false)}}) : React.createElement('button',{onClick:()=>setOpen(true)},'Reopen'); }
        createRoot(document.getElementById('root')).render(React.createElement(I18nContext.Provider,{value:{locale,setLocale:()=>{},t:(key,values)=>translate(locale,key,values)}},React.createElement(Fixture)));
      </script></body></html>`);
      await route.fulfill({ contentType: "text/html", body: html });
    });
    await page.goto(`http://127.0.0.1:43176/__standard_images__?locale=${locale}`);
    await page.waitForFunction(() => window.uiT && document.querySelectorAll('input[type="checkbox"]').length === 3);
    const t = (key) => page.evaluate((key) => window.uiT(key), key);
    const button = async (key) => page.getByRole("button", { name: await t(key), exact: true });
    const click = async (key) => (await button(key)).click();
    assert.equal(await page.getByRole("checkbox", { checked: true }).count(), 1);
    await page.getByRole("checkbox", { name: /task-two/ }).check();
    await click("Install selected project images");
    assert.equal(await page.evaluate(() => window.fixture.requests.filter((row) => row.method === "POST").length), 0, "No download before confirmation");
    const decision = page.getByRole("alertdialog"); await decision.waitFor();
    assert(await decision.evaluate((node) => node.contains(document.activeElement)));
    await page.keyboard.press("Escape"); assert.equal(await decision.count(), 0);
    await click("Install selected project images"); await click("Confirm image installation");
    await (await button("Cancel installation")).waitFor();
    assert.deepEqual(await page.evaluate(() => window.fixture.requests.find((row) => row.path === "/intranet/operations/standard-images").body), { dataset: "fixture", datasetRevision: 'fixture-v1', taskIds: ["task-one", "task-two"], imageSourcesRevision: 0, confirmed: true });
    await click("Cancel installation"); await decision.waitFor(); await decision.getByRole("button", { name: await t("Cancel installation"), exact: true }).click();
    await (await button("Retry / continue installation")).waitFor();
    await click("Retry / continue installation"); await (await button("Cancel installation")).waitFor();
    await page.evaluate(() => { window.fixture.job = { ...window.fixture.job, status: "failed", failure: "Fixture registry unavailable", progress: { percent: 0, log: "layer Downloading 5 MB / 10 MB\nRegistry unavailable. Completed images are kept." } }; });
    await page.getByText("Fixture registry unavailable", { exact: true }).waitFor();
    await click("Close"); await page.getByRole("button", { name: "Reopen" }).click();
    await page.getByText("Fixture registry unavailable", { exact: true }).waitFor();
    const folder = resolve("artifacts/standard-images-ui"); await mkdir(folder, { recursive: true });
    await page.screenshot({ path: resolve(folder, `${locale}.png`) });
    assert.equal(await page.locator('dialog').evaluate((node) => node.scrollWidth > node.clientWidth + 1), false);
    await click("Retry / continue installation"); await (await button("Cancel installation")).waitFor();
    await page.evaluate(() => { window.fixture.job = { ...window.fixture.job, status: "completed", progress: { percent: 100, log: "All selected images installed; tests not yet validated." } }; });
    await page.getByText(await t("Completed without model token usage."), { exact: true }).waitFor();
    await page.waitForFunction(() => document.querySelector('.workbench-form[aria-busy="false"]'));
    assert.equal(await (await button("Install selected project images")).isEnabled(), true);
    const requestsAfterCompletion = await page.evaluate(() => window.fixture.requests.length);
    await page.waitForTimeout(2200);
    assert.equal(await page.evaluate(() => window.fixture.requests.length), requestsAfterCompletion, "Completed jobs stop polling and do not create a refresh loop");
    await page.getByRole('combobox', { name: await t('Company environment profile') }).selectOption('company-v1');
    await page.getByText('registry.example/company/shared:v1', { exact: true }).first().waitFor();
    await click('Check matching tasks in registry');
    await page.getByText(await t('Image not found in registry'), { exact: true }).first().waitFor();
    await click('Select only tasks with available images');
    assert.equal(await page.getByRole('checkbox', { checked: true }).count(), 2);
    assert.equal(await page.getByRole('checkbox', { name: /task-three/ }).isChecked(), false);
    assert.equal(await (await button('Create experiment with selected tasks')).isEnabled(), false);
    assert.equal((await page.evaluate(() => window.fixture.requests.find((row) => row.path === '/intranet/operations/image-check').body)).profileId, 'company-v1');
    await page.evaluate(() => { window.fixture.installed = true; });
    await click('Refresh image status');
    await page.waitForFunction(() => document.querySelector('.workbench-form[aria-busy="false"]'));
    await page.screenshot({ path: resolve(folder, `${locale}-company.png`) });
    await click('Create experiment with selected tasks');
    assert.deepEqual(await page.evaluate(() => window.fixture.selection.taskIds), ['task-one', 'task-two']);
    assert.equal(await page.evaluate(() => window.fixture.selection.profile.id), 'company-v1');
    await page.getByRole('button', { name: 'Reopen' }).click();
    const address = page.getByRole('textbox', { name: `${await t('Full image address or docker pull command')} · upstream/shared:v1`, exact: true });
    const mirror = 'harbor.company.example:5000/bench/planbenchx86:Internal-v2';
    await address.fill('docker pull ' + mirror + ' && echo unsafe');
    assert(await (await button('Install selected project images')).isDisabled());
    await click('Save addresses and refresh');
    await page.getByRole('alert').waitFor();
    assert.equal(await page.evaluate(() => window.fixture.requests.filter((row) => row.method === 'PUT').length), 0, 'Invalid commands must not be saved');
    await address.fill('docker pull ' + mirror);
    await click('Close'); await decision.waitFor(); await click('Keep editing');
    await page.evaluate(() => { window.fixture.conflict = true; });
    await click('Save addresses and refresh');
    await page.getByRole('alert').filter({ hasText: await t('Image addresses changed elsewhere. Refresh image status before saving or installing.') }).waitFor();
    assert.equal(await address.inputValue(), 'docker pull ' + mirror);
    await page.evaluate(() => { window.fixture.conflict = false; window.fixture.sourceRevision++; });
    await click('Refresh image status');
    await page.waitForFunction(() => document.querySelector('.workbench-form[aria-busy="false"]'));
    assert.equal(await address.inputValue(), 'docker pull ' + mirror, 'Refresh must preserve unsaved address input');
    await click('Save addresses and refresh');
    await page.getByText(mirror, { exact: true }).first().waitFor();
    await page.waitForFunction(() => document.querySelector('.workbench-form[aria-busy="false"]'));
    assert.equal(await address.inputValue(), mirror, 'The server stores only a normalized image reference');
    assert.equal(await page.evaluate(() => window.fixture.addresses['upstream/shared:v1']), mirror);
    await page.screenshot({ path: resolve(folder, `${locale}-exact-address.png`) });
    assert.equal(await page.locator('dialog').evaluate((node) => node.scrollWidth > node.clientWidth + 1), false);
    await click('Install selected project images'); await click('Confirm image installation');
    await (await button('Cancel installation')).waitFor();
    assert.equal(await page.evaluate(() => window.fixture.requests.filter((row) => row.path === '/intranet/operations/standard-images').at(-1).body.imageSourcesRevision), 2);
    await click('Close'); await page.getByRole('button', { name: 'Reopen' }).click();
    await page.evaluate(() => { window.fixture.job = { ...window.fixture.job, status: 'completed' }; });
    await page.getByText(await t('Completed without model token usage.'), { exact: true }).waitFor();
    await page.waitForFunction(() => document.querySelector('.workbench-form[aria-busy="false"]'));
    await click('Use default address'); await click('Save addresses and refresh');
    await page.getByText('upstream/shared:v1', { exact: true }).first().waitFor();
    await page.waitForFunction(() => document.querySelector('.workbench-form[aria-busy="false"]'));
    assert.equal(await page.evaluate(() => Object.keys(window.fixture.addresses).length), 0);
    await click("Close"); await page.evaluate(() => { window.fixture.oldService = true; });
    await page.getByRole("button", { name: "Reopen" }).click();
    await page.getByText(await t("Project image installation requires the matching newer local evaluation service image. Update Application images in Settings first."), { exact: true }).waitFor();
    assert.deepEqual(errors, []);
    console.log(`${locale}: selection, consent, cancellation, retry, full pull address editing, conflicts, reset, frozen source revision, completion and upgrade guidance passed`);
    await page.close();
  }
} finally { await browser?.close(); await server.close(); }
