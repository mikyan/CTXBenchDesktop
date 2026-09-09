/** Isolated bilingual interaction checks. All service/native calls are fixtures; no model calls. */
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { mkdir } from 'node:fs/promises';
import { resolve } from 'node:path';
import { createServer } from 'vite';

const { chromium } = createRequire(import.meta.url)('playwright');
const server = await createServer({ server: { host: '127.0.0.1', port: 43176, strictPort: true }, logLevel: 'error' });
await server.listen();
let browser;
try {
  browser = await chromium.launch({ headless: true, ...(process.env.CTXBENCH_BROWSER_CHANNEL ? { channel: process.env.CTXBENCH_BROWSER_CHANNEL } : {}) });
  for (const locale of ['en', 'zh-CN']) {
    const page = await browser.newPage({ viewport: { width: 1100, height: 800 } });
    page.setDefaultTimeout(15000);
    const errors = []; page.on('pageerror', (error) => errors.push(error.message));
    await page.route('**/worker/**', (route) => route.abort());
    await page.addInitScript(() => {
      const row = (id) => ({ id, repository: 'https://git.example/team/service.git', baseCommit: 'a'.repeat(40), prompt: 'Original expected behavior.', image: 'company/test:v1', test: { command: ['python3', '-m', 'unittest'], hiddenPatch: 'EVAL_ONLY_TEST' }, goldPatch: 'EVAL_ONLY_GOLD' });
      const make = (id, name, input = row(id), revision = 1) => ({ id: 'case-' + id, name, benchmark: 'custom', revision, taskId: input.id, repository: input.repository, baseCommit: input.baseCommit, prompt: input.prompt, image: input.image, modified: false, createdAt: '2026-09-08', updatedAt: '2026-09-08', row: input, usedBy: [] });
      const cases = [make('one', 'Backend API'), make('two', 'Backend validation')];
      const sets = [{ id: 'set-main', name: 'Backend suite', revision: 1, caseIds: ['case-one', 'case-two'], benchmark: 'custom', count: 2, createdAt: '2026-09-08', updatedAt: '2026-09-08' }];
      const snapshot = { id: 'snapshot-original', sourceId: 'case-one', name: 'Original snapshot', sourceRevision: 1, contentRevision: 'revision-one', dataset: 'frozen-hash', benchmark: 'custom', createdAt: '2026-09-08', members: [{ caseId: 'case-one', revision: 1, taskId: 'one', rowHash: 'row-hash', modified: false }] };
      window.fixture = { cases, sets, calls: [], conflict: false, staleRun: false, libraryUnavailable: true, importWarnings: [] };
      localStorage.setItem('ctxbench-distribution', 'Ubuntu');
      window.__TAURI_INTERNALS__ = { invoke: async (command, args) => {
        window.fixture.calls.push({ command, ...structuredClone(args) });
        if (command === 'list_local_images') return { images: ['company/test:v1', 'ctxbench/agent-pi:0.1.0'] };
        if (command === 'save_export') return 'fixture-export.json';
        if (command !== 'worker_request') throw Error('Unexpected native call: ' + command);
        const { path, method, body } = args;
        const publicCase = ({ row, usedBy, ...item }) => item;
        if (path === '/library') {
          if (window.fixture.libraryUnavailable) throw Error('A case definition must not exceed 10 MB.');
          return { version: 1, cases: cases.map(publicCase), sets, importWarnings: window.fixture.importWarnings };
        }
        if (path.startsWith('/library/cases/')) {
          const item = cases.find((value) => value.id === path.split('/').at(-1));
          if (method === 'GET') return { ...item, usedBy: sets.filter((value) => value.caseIds.includes(item.id)).map(({ id, name }) => ({ id, name })) };
          if (window.fixture.conflict) throw Error('This item was edited elsewhere. Reload it before saving; your changes were not overwritten.');
          assertRevision(body.expectedRevision === item.revision);
          Object.assign(item, make(item.id.slice(5), body.name, body.row, item.revision + 1));
          return publicCase(item);
        }
        if (path === '/library/cases' && method === 'POST') { const item = make('new', body.name, body.row); cases.push(item); return publicCase(item); }
        if (path.startsWith('/library/sets/')) { const item = sets.find((value) => value.id === path.split('/').at(-1)); assertRevision(body.expectedRevision === item.revision); Object.assign(item, { name: body.name, caseIds: body.caseIds, count: body.caseIds.length, revision: item.revision + 1 }); return item; }
        if (path === '/library/sets' && method === 'POST') { const item = { ...sets[0], ...body, id: 'set-new', revision: 1, count: body.caseIds.length }; sets.push(item); return item; }
        if (path.startsWith('/library/selections/')) {
          const key = path.split('/').at(-1); const item = key.startsWith('case-') ? cases.find((value) => value.id === key) : sets.find((value) => value.id === key);
          const members = key.startsWith('case-') ? [item] : item.caseIds.map((id) => cases.find((value) => value.id === id));
          return { dataset: { ...publicCase(item), count: members.length }, tasks: members.map((value) => ({ ...publicCase(value), id: value.taskId, caseId: value.id, caseRevision: value.revision })), revision: 'selection-' + members.map((value) => value.revision).join('-') };
        }
        if (path === '/library/snapshots') return [snapshot];
        if (path === '/library/snapshots/snapshot-original') { const { test, goldPatch, ...task } = row('one'); return { ...snapshot, tasks: [task] }; }
        if (path === '/runtime') return { credentials: [{ name: 'XIAOMI_TOKEN_PLAN_CN_API_KEY', configured: true }], projectEnvironmentVersion: 1, defaultPrompts: { builder: 'DEFAULT_BASELINE_ONLY_PROMPT' } };
        if (['/intranet/profiles', '/token-budgets', '/constraint-packages'].includes(path)) return [];
        if (path === '/prepare/context') { if (window.fixture.staleRun) throw Error('The selected cases or dataset changed. Reload the selection and review it before starting.'); return { id: 'op-new' }; }
        if (path === '/preflight') return { runs: 2, builderInvocations: 1, minerInvocations: 0, judgeInvocations: 0, configuredTokenAllowance: 15000000, storage: { freeBytes: 1e11, ready: true } };
        throw Error('Unexpected fixture path: ' + path);
        function assertRevision(condition) { if (!condition) throw Error('Fixture received the wrong optimistic revision'); }
      } };
    });
    await page.route('**/__case_library_fixture__*', async (route) => {
      if (!route.request().isNavigationRequest()) return route.continue();
      const html = await server.transformIndexHtml('/__case_library_fixture__', `<!doctype html><html><head><meta charset="UTF-8" /></head><body><main id="root"></main><script type="module">
        import React,{useState} from 'react'; import {createRoot} from 'react-dom/client';
        import {DatasetsPage} from '/src/pages/DatasetsPage.tsx'; import {PreparationDialog} from '/src/components/WorkbenchDialogs.tsx'; import {ExperimentComposer} from '/src/components/ExperimentComposer.tsx';
        import {I18nContext} from '/src/i18n.context.ts'; import {translate} from '/src/i18n.tsx'; import '/src/styles.css'; import '/src/ux.css';
        const locale = new URLSearchParams(location.search).get('locale'); window.uiT = (key) => translate(locale,key);
        function Fixture() { const [source,setSource] = useState(''); const [kind,setKind] = useState('');
          return React.createElement(React.Fragment,null,React.createElement(DatasetsPage,{initialView:'cases',snapshot:{datasets:[]},onImport:()=>{},onGenerate:(id)=>{setSource(id);setKind('context');},onExperiment:(id)=>{setSource(id);setKind('experiment');}}),
            kind==='context'&&React.createElement(PreparationDialog,{kind:'context',initialSource:source,onClose:()=>setKind(''),onComplete:()=>{window.prepared=true;}}),
            kind==='experiment'&&React.createElement(ExperimentComposer,{creating:false,initialDataset:source,artifacts:[],onClose:()=>setKind(''),onCreate:async(request)=>{window.experiment=request;setKind('');}})); }
        createRoot(document.getElementById('root')).render(React.createElement(I18nContext.Provider,{value:{locale,setLocale:()=>{},t:(key,values)=>translate(locale,key,values)}},React.createElement(Fixture)));
      </script></body></html>`);
      await route.fulfill({ contentType: 'text/html', body: html });
    });
    await page.goto(`http://127.0.0.1:43176/__case_library_fixture__?locale=${locale}`);
    const t = (key) => page.evaluate((value) => window.uiT(value), key);
    const button = async (key) => (await page.locator('dialog[open]').count() ? page.locator('dialog[open]').last() : page).getByRole('button', { name: await t(key), exact: true });
    const click = async (key) => (await button(key)).click();
    const field = async (key) => page.getByRole(['Choose an installed image', 'Test environment', 'Evaluation source'].includes(key) ? 'combobox' : 'textbox', { name: await t(key), exact: true });
    await page.getByRole('alert').filter({ hasText: await t('A case definition must not exceed 10 MB.') }).waitFor();
    assert(await (await button('Create evaluation case')).isEnabled());
    assert.equal(await page.getByRole('heading', { name: await t('No evaluation cases yet'), exact: true }).count(), 0, 'A load failure is not an empty library');
    assert(!(await page.locator('body').innerText()).includes('EVAL_ONLY_GOLD'));
    await click('Create evaluation case');
    await (await field('Case name')).fill('New service case');
    await (await field('Repository URL / worker path')).fill('https://git.example/team/new.git');
    await (await field('Baseline commit (40 characters)')).fill('b'.repeat(40));
    await (await field('Choose an installed image')).selectOption('company/test:v1');
    await click('Next');
    await (await field('Task ID')).fill('new-task');
    await (await field('Task prompt · agent-visible')).fill('Fix the API response validation.');
    await (await field('Test command')).fill('python3 -m unittest');
    await click('Next'); await click('Save evaluation case');
    await page.locator('dialog[open]').waitFor({ state: 'hidden' });
    assert.equal(await page.evaluate(() => window.fixture.cases.length), 3, 'Independent creation must work despite a library listing failure');
    await page.evaluate(() => {
      window.fixture.libraryUnavailable = false;
      window.fixture.importWarnings = [{ datasetId: 'broken-source', name: 'Unavailable imported suite', code: 'import-source-unavailable', message: 'This imported dataset could not be loaded. Its source is missing or failed validation. Restore the original data directory and refresh; other cases remain available.' }];
    });
    await click('Refresh');
    await page.getByRole('heading', { name: 'New service case', exact: true }).waitFor();
    await page.getByRole('status').filter({ hasText: await t('Some imported datasets could not be loaded') }).waitFor();
    assert((await page.locator('body').innerText()).includes('Unavailable imported suite'));
    assert.equal(await page.getByRole('alert').count(), 0, 'Refresh clears the old load error');
    assert(await (await button('Create evaluation case')).isEnabled());
    await page.evaluate(() => { window.fixture.importWarnings = []; });
    await click('Refresh');
    await page.getByRole('status').filter({ hasText: await t('Some imported datasets could not be loaded') }).waitFor({ state: 'hidden' });
    assert.equal(await page.evaluate(() => window.fixture.sets.length), 1, 'Creating a case must not create a set');
    const card = (name) => page.locator('article.dataset-card').filter({ has: page.getByRole('heading', { name, exact: true }) });
    await card('Backend API').getByRole('button', { name: await t('Edit evaluation case'), exact: true }).click();
    await (await field('Case name')).fill('Edited backend');
    await page.evaluate(() => { window.fixture.conflict = true; });
    await click('Next'); await click('Next'); await click('Save case changes');
    await page.getByRole('alert').filter({ hasText: await t('This item was edited elsewhere. Reload it before saving; your changes were not overwritten.') }).waitFor();
    assert.equal(await (await field('Case name')).inputValue(), 'Edited backend', 'Conflict must preserve unsaved input');
    await page.evaluate(() => { window.fixture.conflict = false; });
    await click('Save case changes');
    await page.getByRole('heading', { name: 'Edited backend', exact: true }).waitFor();
    await click('Datasets'); await click('Compose dataset');
    await (await field('Dataset name')).fill('Selected backend cases');
    await page.getByRole('checkbox', { name: /Edited backend/ }).check();
    await (await field('Search evaluation cases')).fill('validation');
    await page.getByRole('checkbox', { name: /Backend validation/ }).check();
    await click('Create dataset');
    await page.getByRole('heading', { name: 'Selected backend cases', exact: true }).waitFor();
    assert.deepEqual(await page.evaluate(() => window.fixture.sets.at(-1).caseIds), ['case-one', 'case-two']);
    await card('Selected backend cases').getByRole('button', { name: await t('Edit dataset composition'), exact: true }).click();
    await (await button('Remove from dataset')).first().click();
    await click('Close');
    await page.getByRole('alertdialog').waitFor();
    await click('Keep editing');
    await (await field('Dataset name')).fill('Renamed suite');
    await click('Save dataset changes');
    assert.equal(await page.evaluate(() => window.fixture.cases.length), 3, 'Removing membership must preserve cases');
    await click('Evaluation cases');
    await card('Edited backend').getByRole('button', { name: await t('Generate context'), exact: true }).click();
    await page.waitForFunction(() => document.querySelector('.library-source select')?.value === 'case-one');
    await page.waitForFunction(() => Array.from(document.querySelectorAll('select')).some((select) => select.value === 'one'));
    assert.equal(await (await field('Provider')).inputValue(), 'xiaomi-token-plan-cn');
    await page.evaluate(() => { window.fixture.staleRun = true; });
    await click('Submit');
    await page.getByRole('alert').filter({ hasText: await t('The selected cases or dataset changed. Reload the selection and review it before starting.') }).waitFor();
    await page.evaluate(() => { window.fixture.staleRun = false; });
    await click('Reload current selection');
    await page.waitForFunction(() => Array.from(document.querySelectorAll('select')).some((select) => select.value === 'one'));
    await click('Submit');
    await page.waitForFunction(() => window.prepared);
    const preparation = await page.evaluate(() => window.fixture.calls.find((call) => call.path === '/prepare/context').body);
    assert.equal(preparation.dataset, 'case-one'); assert.equal(preparation.datasetRevision, 'selection-2'); assert.equal(preparation.taskId, 'one');
    assert.equal(preparation.workflow.steps[0].prompt, null); assert.deepEqual(preparation.envNames, ['XIAOMI_TOKEN_PLAN_CN_API_KEY']);
    await card('Edited backend').getByRole('button', { name: await t('New experiment'), exact: true }).click();
    await (await field('Experiment name')).fill('Snapshot-backed run');
    await page.waitForFunction(() => document.querySelector('.task-picker input[type="checkbox"]')?.checked);
    await click('Continue to execution'); await click('Continue to review'); await click('Create & prepare');
    await page.waitForFunction(() => window.experiment);
    const experiment = await page.evaluate(() => window.experiment);
    assert.equal(experiment.dataset, 'case-one'); assert.equal(experiment.datasetRevision, 'selection-2');
    assert.deepEqual(experiment.taskIds, ['one']); assert.deepEqual(experiment.arms, ['none', 'skill-generated']);
    await click('Run snapshots'); await click('View run snapshot');
    await page.getByRole('heading', { name: 'Original snapshot', exact: true }).waitFor();
    await page.locator('dialog details').first().locator('summary').click();
    assert((await page.locator('dialog').innerText()).includes('Original expected behavior.'));
    assert(!(await page.locator('dialog').innerText()).includes('EVAL_ONLY_GOLD'));
    await click('Close'); await click('Evaluation cases');
    await page.evaluate(() => {
      const item = structuredClone(window.fixture.cases[0]);
      item.id = 'case-legacy'; item.name = 'Legacy complex case'; item.taskId = 'legacy-task'; item.revision = 1;
      item.row.id = item.taskId; item.row.build = { dockerfile: 'Dockerfile', context: '.', args: {} };
      window.fixture.cases.push(item);
    });
    await click('Refresh');
    await card('Legacy complex case').getByRole('button', { name: await t('Edit evaluation case'), exact: true }).click();
    await (await field('Case definition JSON')).waitFor();
    await (await field('Case name')).fill('Preserved legacy definition');
    await click('Save case changes');
    await page.getByRole('heading', { name: 'Preserved legacy definition', exact: true }).waitFor();
    const legacy = await page.evaluate(() => window.fixture.cases.find((item) => item.id === 'case-legacy'));
    assert.equal(legacy.row.build.dockerfile, 'Dockerfile'); assert.equal(legacy.row.image, 'company/test:v1');
    assert.equal(legacy.row.goldPatch, 'EVAL_ONLY_GOLD'); assert.equal(legacy.revision, 2);
    await page.setViewportSize({ width: 1060, height: 680 });
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'No horizontal clipping at minimum desktop size');
    await mkdir(resolve('artifacts/case-library-ui'), { recursive: true });
    await page.screenshot({ path: resolve(`artifacts/case-library-ui/${locale}.png`), fullPage: true });
    await page.evaluate(() => { window.fixture.cases.length = 0; window.fixture.sets.length = 0; });
    await click('Refresh');
    await page.getByRole('heading', { name: await t('No evaluation cases yet'), exact: true }).waitFor();
    assert(await (await button('Create evaluation case')).isEnabled());
    await click('Datasets');
    await page.getByRole('heading', { name: await t('No datasets yet'), exact: true }).waitFor();
    await page.getByText(await t('Create a case or import standard cases first, then compose a dataset here.'), { exact: true }).waitFor();
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ locale, passed: true, createsDespiteListFailure: true, partialImportWarnings: true, refreshRecovers: true, emptyLibraryUsable: true, createsIndependentCase: true, editsWithRevision: true, composesReferences: true, directGeneration: true, snapshotBoundExperiment: true }));
    await page.close();
  }
} catch (error) {
  const page = browser?.contexts().flatMap((context) => context.pages()).at(-1);
  if (page) { await mkdir(resolve('artifacts/case-library-ui'), { recursive: true }); await page.screenshot({ path: resolve('artifacts/case-library-ui/failure.png'), fullPage: true }); console.error((await page.locator('body').innerText()).slice(-5000)); }
  throw error;
} finally { await browser?.close(); await server.close(); }
