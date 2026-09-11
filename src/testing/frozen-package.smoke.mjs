/** Frozen package UX regression. Isolated browser; service/native calls are fixtures. */
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { createServer } from 'vite';

const { chromium } = createRequire(import.meta.url)('playwright');
const server = await createServer({ server: { host: '127.0.0.1', port: 43188, strictPort: true }, logLevel: 'error' });
await server.listen();
let browser;
try {
  browser = await chromium.launch({ headless: true, ...(process.env.CTXBENCH_BROWSER_CHANNEL ? { channel: process.env.CTXBENCH_BROWSER_CHANNEL } : {}) });
  for (const locale of ['en', 'zh-CN']) {
    const page = await browser.newPage({ viewport: { width: 1120, height: 800 } });
    page.setDefaultTimeout(10000);
    const errors = []; page.on('pageerror', error => errors.push(error.message));
    await page.route('**/worker/**', route => route.abort());
    await page.addInitScript(() => {
      const task = { id: 'fixture-task', name: 'Fixture case', taskId: 'fixture-task', repository: 'https://git.example/backend', baseCommit: 'a'.repeat(40), benchmark: 'custom', revision: 1, customAgentImage: 'fixture/agent:v1', image: 'fixture/tests:v1', prompt: 'Fix the specified behavior.' };
      window.fixture = { calls: [], available: [], task };
      window.__TAURI_INTERNALS__ = { invoke: async (command, args) => {
        window.fixture.calls.push({ command, args });
        if (command !== 'worker_request') throw Error('Unexpected native call: ' + command);
        const { path, method, body } = args;
        if (path === '/library') return { version: 1, sets: [], cases: [{ ...task, id: 'case-fixture' }] };
        if (path === '/library/selections/case-fixture') return { dataset: { ...task, id: 'case-fixture', count: 1 }, revision: 'rev-1', tasks: [task] };
        if (path === '/runtime') return { credentials: [], projectEnvironmentVersion: 1 };
        if (path === '/token-budgets' || path === '/constraint-packages' || path === '/intranet/profiles' || path.startsWith('/ci/selection/')) return [];
        if (path.includes('/project-image-sources')) return { overrides: [] };
        if (path === '/context/import' && method === 'POST') {
          window.fixture.imported = body;
          window.fixture.available = [{ id: 'fixture-package', repository: task.repository, commit: task.baseCommit, status: 'ready', source: 'manual', files: 1 }];
          return { id: 'fixture-package' };
        }
        throw Error('Unexpected service call: ' + path);
      } };
    });
    await page.route('**/__package_fixture__*', async route => {
      if (!route.request().isNavigationRequest()) return route.continue();
      const body = await server.transformIndexHtml('/__package_fixture__', `<!doctype html><html><head><meta charset="UTF-8" /></head><body><main id="root"></main><script type="module">
        import React,{useState} from 'react'; import {createRoot} from 'react-dom/client';
        import {ExperimentComposer} from '/src/components/ExperimentComposer.tsx';
        import {I18nContext} from '/src/i18n.context.ts'; import {translate} from '/src/i18n.tsx'; import '/src/styles.css'; import '/src/ux.css';
        const locale=new URLSearchParams(location.search).get('locale'); window.uiT=key=>translate(locale,key);
        function Fixture(){const [data,setData]=useState({artifacts:[],error:false});window.fixture.setData=setData;
          return React.createElement(ExperimentComposer,{creating:false,initialDataset:'case-fixture',artifacts:data.artifacts,artifactLoadError:data.error,
            onRefreshArtifacts:async()=>{if(window.fixture.deferRefresh)await new Promise(resolve=>window.fixture.releaseRefresh=resolve);if(window.fixture.failRefresh){setData(old=>({...old,error:true}));throw Error('Fixture unavailable');}setData({artifacts:window.fixture.available,error:false});},
            onClose:()=>{},onCreate:async request=>{window.fixture.experiment=request}});}
        createRoot(document.getElementById('root')).render(React.createElement(I18nContext.Provider,{value:{locale,setLocale:()=>{},t:(key,values)=>translate(locale,key,values)}},React.createElement(Fixture)));
      </script></body></html>`);
      await route.fulfill({ contentType: 'text/html', body });
    });
    await page.goto(`http://127.0.0.1:43188/__package_fixture__?locale=${locale}`, { timeout: 30000, waitUntil: 'domcontentloaded' });
    const t = key => page.evaluate(key => window.uiT(key), key);
    const experiment = page.getByRole('dialog', { name: await t('New experiment'), exact: true });
    await experiment.getByRole('textbox', { name: await t('Experiment name'), exact: true }).fill('Keep my experiment draft');
    await experiment.getByRole('combobox', { name: await t('Context comparison'), exact: true }).selectOption('manual');
    const packages = experiment.getByRole('group', { name: await t('Frozen knowledge packages'), exact: true });
    const selector = packages.getByRole('combobox', { name: 'fixture-task', exact: true });
    await packages.getByText(await t('No knowledge packages have been imported or generated yet.'), { exact: true }).waitFor();
    assert((await packages.innerText()).includes('a'.repeat(40)));
    assert((await packages.innerText()).includes('https://git.example/backend'));
    await page.evaluate(() => { window.fixture.deferRefresh = true; window.fixture.failRefresh = true; });
    await packages.getByRole('button', { name: await t('Refresh knowledge packages'), exact: true }).click();
    await packages.getByText(await t('Loading knowledge packages…'), { exact: true }).waitFor();
    assert.equal(await packages.getByText(await t('No knowledge packages have been imported or generated yet.'), { exact: true }).count(), 0);
    assert(await selector.isDisabled());
    await page.evaluate(() => { window.fixture.releaseRefresh(); });
    await packages.getByRole('alert').waitFor();
    assert.equal(await packages.getByText(await t('No knowledge packages have been imported or generated yet.'), { exact: true }).count(), 0, 'A failed read is not an empty collection');
    await page.evaluate(() => { window.fixture.failRefresh = false; window.fixture.deferRefresh = false; });
    await packages.getByRole('button', { name: await t('Refresh knowledge packages'), exact: true }).click();
    await packages.getByText(await t('No knowledge packages have been imported or generated yet.'), { exact: true }).waitFor();
    await packages.getByRole('button', { name: await t('Import a matching package'), exact: true }).click();
    const importer = page.getByRole('dialog', { name: await t('Import package'), exact: true });
    await importer.waitFor();
    assert.equal(await page.locator('dialog[open]').count(), 2, 'Import opens above the existing experiment, not instead of it');
    await page.keyboard.press('Escape'); await importer.waitFor({ state: 'detached' });
    assert.equal(await experiment.getByRole('textbox', { name: await t('Experiment name'), exact: true }).inputValue(), 'Keep my experiment draft');
    await packages.getByRole('button', { name: await t('Import a matching package'), exact: true }).click();
    await importer.getByRole('textbox', { name: await t('Package baseline commit'), exact: true }).fill('a'.repeat(40));
    await importer.getByLabel(await t('Package JSON: relative paths mapped to text'), { exact: true }).setInputFiles({ name: 'fixture-context.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify({ 'docs/overview.md': 'Baseline architecture only.' })) });
    await importer.getByText('docs/overview.md', { exact: false }).waitFor();
    await importer.getByRole('button', { name: await t('Submit'), exact: true }).click();
    await importer.waitFor({ state: 'detached' });
    await selector.locator('option[value="fixture-package"]').waitFor({ state: 'attached' });
    assert.equal(await selector.inputValue(), '', 'Import never automatically chooses the experimental treatment');
    assert.equal(await experiment.getByRole('textbox', { name: await t('Experiment name'), exact: true }).inputValue(), 'Keep my experiment draft');
    await selector.selectOption('fixture-package');
    await experiment.getByRole('button', { name: await t('Continue to execution'), exact: true }).click();
    await experiment.getByRole('button', { name: await t('Continue to review'), exact: true }).click();
    const imageReview = experiment.getByRole('group', { name: await t('Coding Agent images by task'), exact: true });
    assert((await imageReview.innerText()).includes('fixture/agent:v1'));
    assert(!(await imageReview.innerText()).includes('ctxbench/agent-pi:0.1.0'), 'Custom coding image must not be described as the Pi default');
    assert((await imageReview.innerText()).includes(await t('Case override — uses the custom command and image.')));
    await experiment.getByRole('button', { name: await t('Create & prepare'), exact: true }).click();
    await page.waitForFunction(() => !!window.fixture.experiment);
    assert.deepEqual(await page.evaluate(() => window.fixture.experiment.contextArtifacts), { 'fixture-task': 'fixture-package' });
    assert.equal(await page.evaluate(() => window.fixture.imported.taskId), 'fixture-task');
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ locale, loadingAndFailureNotEmpty: true, nestedImportPreservesDraft: true, noAutomaticPackageSelection: true, explicitSelectionSubmitted: true, effectiveCodingImageInReview: true, realServiceCalls: 0 }));
    await page.close();
  }
} finally { await browser?.close(); await server.close(); }
