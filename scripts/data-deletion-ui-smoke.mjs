/** Bilingual, isolated UI checks. Every native/service request is a fixture; no user data is touched. */
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { mkdir } from 'node:fs/promises';
import { resolve } from 'node:path';
import { createServer } from 'vite';

const { chromium } = createRequire(import.meta.url)('playwright');
const server = await createServer({ server: { host: '127.0.0.1', port: 43181, strictPort: true }, logLevel: 'error' });
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
      const cases = ['one', 'two'].map((id) => ({ id: 'case-' + id, name: 'Backend ' + id, benchmark: 'custom', revision: 1, taskId: id,
        repository: 'https://git.example/team/backend.git', baseCommit: 'a'.repeat(40), prompt: 'Fix behavior.', image: 'company/test:v1', modified: false }));
      const sets = [{ id: 'set-main', name: 'Backend suite', caseIds: cases.map((item) => item.id), revision: 1, count: 2, benchmark: 'custom' }];
      const snapshots = [{ id: 'snapshot-old', name: 'Original source snapshot', sourceId: 'set-main', sourceRevision: 1, contentRevision: 'frozen-revision', dataset: 'frozen-hash', benchmark: 'custom', createdAt: '2026-09-09', members: cases.map((item) => ({ caseId: item.id, revision: 1, taskId: item.taskId, rowHash: 'hash', modified: false })) }];
      window.fixture = { cases, sets, snapshots, calls: [], mode: '', deletedCount: 0 };
      window.__TAURI_INTERNALS__ = { invoke: async (command, args) => {
        const f = window.fixture;
        f.calls.push({ command, ...structuredClone(args) });
        if (command !== 'worker_request') throw Error('Unexpected native call: ' + command);
        const { path, body } = args;
        if (path === '/library') return structuredClone({ cases: f.cases, sets: f.sets });
        if (path === '/library/snapshots') return structuredClone(f.snapshots);
        if (path.startsWith('/container-logs?')) return { sessions: [], nextBefore: null };
        if (path.startsWith('/run-record?')) return structuredClone(f.snapshot.runs.find((run) => run.id === new URLSearchParams(path.split('?')[1]).get('id')));
        if (path === '/data-deletions/preview') {
          if (f.mode === 'old') throw Error('Not Found');
          if (f.mode === 'loading') await new Promise((done) => { f.releasePreview = done; });
          const plan = { ...body, token: 'a'.repeat(64), blockers: [], affectedSets: [], runCount: 0 };
          if (body.kind === 'case') {
            const item = f.cases.find((value) => value.id === body.id);
            plan.name = item.name;
            plan.affectedSets = f.sets.filter((value) => value.caseIds.includes(body.id)).map((value) => ({ ...value, remainingCount: value.count - 1 }));
          } else if (body.kind === 'set') {
            const item = f.sets.find((value) => value.id === body.id);
            plan.name = item.name; plan.caseCount = item.count;
          } else {
            const run = body.kind === 'result' && f.snapshot.runs.find((value) => value.id === body.id);
            const experiment = f.snapshot.experiments.find((value) => value.id === (run ? run.experimentId : body.id));
            plan.name = experiment.name;
            plan.runCount = f.snapshot.runs.filter((value) => value.experimentId === experiment.id && (!run || value.pairId === run.pairId)).length;
            if (run) Object.assign(plan, { taskId: run.taskId, repeat: run.repeat, pairId: run.pairId });
            if (experiment.status === 'running') plan.blockers.push('Finish or cancel this experiment and wait for its current operation to exit before deleting results.');
          }
          return plan;
        }
        if (path === '/data-deletions') {
          if (f.mode === 'stale') throw Error('The deletion scope changed. Reload the preview and confirm the updated impact; nothing was deleted.');
          if (f.mode === 'busy') await new Promise((done) => { f.releaseDelete = done; });
          if (body.kind === 'case') {
            f.cases = f.cases.filter((value) => value.id !== body.id);
            f.sets = f.sets.map((value) => { const ids = value.caseIds.filter((id) => id !== body.id); return { ...value, caseIds: ids, count: ids.length, revision: value.revision + 1 }; });
          } else if (body.kind === 'set') f.sets = f.sets.filter((value) => value.id !== body.id);
          else if (body.kind === 'experiment') {
            f.snapshot.experiments = f.snapshot.experiments.filter((value) => value.id !== body.id);
            f.snapshot.runs = f.snapshot.runs.filter((value) => value.experimentId !== body.id);
          } else {
            const run = f.snapshot.runs.find((value) => value.id === body.id);
            f.snapshot.runs = f.snapshot.runs.filter((value) => value.pairId !== run.pairId);
            const exp = f.snapshot.experiments.find((value) => value.id === run.experimentId);
            exp.deletedResultGroups = (exp.deletedResultGroups ?? 0) + 1;
            exp.deletedResultRuns = (exp.deletedResultRuns ?? 0) + 2;
            exp.totalRuns -= 2; exp.completedRuns -= 2;
          }
          f.deletedCount++;
          return { deleted: true, filesRetained: true };
        }
        throw Error('Unexpected fixture path: ' + path);
      } };
    });
    await page.route('**/__deletion_fixture__*', async (route) => {
      if (!route.request().isNavigationRequest()) return route.continue();
      const html = await server.transformIndexHtml('/__deletion_fixture__', `<!doctype html><html><head><meta charset="UTF-8" /></head><body><main id="root"></main><script type="module">
        import React,{useState} from 'react'; import {createRoot} from 'react-dom/client';
        import {DatasetsPage} from '/src/pages/DatasetsPage.tsx'; import {ExperimentsPage} from '/src/pages/ExperimentsPage.tsx'; import {RunDialog} from '/src/components/WorkbenchDialogs.tsx';
        import {createDemoSnapshot} from '/src/data/demo.ts'; import {I18nContext} from '/src/i18n.context.ts'; import {translate} from '/src/i18n.tsx'; import '/src/styles.css'; import '/src/ux.css';
        const locale = new URLSearchParams(location.search).get('locale'); window.uiT = (key) => translate(locale,key);
        const snapshot = createDemoSnapshot(); snapshot.runtime='desktop'; snapshot.datasets=[]; snapshot.tokenBudgets=[];
        const base = {...snapshot.experiments[0],benchmark:'custom',arms:['none','manual'],tasks:1,repeats:2,totalRuns:4,completedRuns:4,status:'completed'};
        snapshot.experiments=[{...base,id:'exp-done',name:'Completed backend'},{...base,id:'exp-active',name:'Running backend',status:'running'}];
        snapshot.runs=[1,2].flatMap(repeat=>['none','manual'].map(arm=>({...snapshot.runs[0],id:'exp-done:one:'+repeat+':'+arm,pairId:'exp-done:one:'+repeat,experimentId:'exp-done',taskId:'one',repeat,arm,mock:false})));
        window.fixture.snapshot=snapshot;
        function Fixture() { const [view,setView]=useState('library'),[data,setData]=useState(structuredClone(snapshot)),[run,setRun]=useState();
          const refresh=()=>setData(structuredClone(window.fixture.snapshot));
          return React.createElement(React.Fragment,null,
            React.createElement('button',{onClick:()=>setView('library')},'Show library'),React.createElement('button',{onClick:()=>setView('experiments')},'Show experiments'),
            view==='library'?React.createElement(DatasetsPage,{snapshot:data,initialView:'cases',onImport:()=>{},onExperiment:()=>{}}):React.createElement(ExperimentsPage,{snapshot:data,onNewExperiment:()=>{},onExport:()=>{},onDatasets:()=>{},onAction:()=>{},onRun:setRun,onDeleted:refresh}),
            run&&React.createElement(RunDialog,{run,onClose:()=>setRun(undefined),onDeleted:refresh})); }
        createRoot(document.getElementById('root')).render(React.createElement(I18nContext.Provider,{value:{locale,setLocale:()=>{},t:(key,values)=>translate(locale,key,values)}},React.createElement(Fixture)));
      </script></body></html>`);
      await route.fulfill({ contentType: 'text/html', body: html });
    });
    await page.goto(`http://127.0.0.1:43181/__deletion_fixture__?locale=${locale}`);
    const t = (key) => page.evaluate((value) => window.uiT(value), key);
    const dialog = () => page.getByRole('alertdialog');
    const button = async (key, scope = page) => scope.getByRole('button', { name: await t(key), exact: true });
    const click = async (key, scope = page) => (await button(key, scope)).click();
    const card = (name) => page.locator('article').filter({ has: page.getByRole('heading', { name, exact: true }) });
    const gone = async () => dialog().waitFor({ state: 'hidden' });
    await card('Backend one').waitFor();
    await page.evaluate(() => { window.fixture.mode = 'loading'; });
    await click('Delete evaluation case', card('Backend one'));
    assert(await (await button('Confirm deletion', dialog())).isDisabled(), 'Preview loading must disable deletion');
    await page.waitForFunction(() => !!window.fixture.releasePreview);
    await page.evaluate(() => { window.fixture.mode = ''; window.fixture.releasePreview(); });
    await dialog().getByText('Backend suite', { exact: false }).waitFor();
    assert.equal(await page.evaluate(() => document.activeElement?.textContent), await t('Keep data'), 'Safe action gets focus');
    await page.keyboard.press('Escape'); await gone();
    assert.equal(await page.evaluate(() => window.fixture.deletedCount), 0, 'Escape must not delete');
    assert.equal(await page.evaluate(() => document.activeElement?.textContent), await t('Delete evaluation case'));

    await page.evaluate(() => { window.fixture.mode = 'stale'; });
    await click('Delete evaluation case', card('Backend one')); await click('Confirm deletion', dialog());
    await dialog().getByRole('alert').waitFor();
    assert(await (await button('Confirm deletion', dialog())).isDisabled(), 'A conflict needs a fresh preview and a new confirmation');
    assert.equal(await page.evaluate(() => window.fixture.cases.length), 2);
    await page.evaluate(() => { window.fixture.mode = 'busy'; });
    await click('Reload deletion preview', dialog());
    await click('Confirm deletion', dialog());
    await page.waitForFunction(() => !!window.fixture.releaseDelete);
    assert(await (await button('Keep data', dialog())).isDisabled());
    assert(await (await button('Confirm deletion', dialog())).isDisabled());
    await page.keyboard.press('Escape'); assert.equal(await dialog().count(), 1, 'Do not dismiss an in-flight deletion');
    await page.evaluate(() => { window.fixture.mode = ''; window.fixture.releaseDelete(); });
    await gone(); await card('Backend one').waitFor({ state: 'hidden' });
    assert.equal(await page.evaluate(() => window.fixture.sets[0].count), 1);
    await click('Datasets'); await click('Delete dataset', card('Backend suite'));
    await dialog().getByText(/independent cases|独立用例/).waitFor();
    const output = resolve('artifacts/data-deletion-ui'); await mkdir(output, { recursive: true });
    await page.screenshot({ path: resolve(output, `${locale}-dataset-confirm.png`), fullPage: true });
    await click('Confirm deletion', dialog()); await gone(); await card('Backend suite').waitFor({ state: 'hidden' });
    assert.equal(await page.evaluate(() => window.fixture.cases.length), 1, 'Deleting a set keeps its cases');
    await (await button('Evaluation cases')).first().click(); await card('Backend two').waitFor();
    await page.evaluate(() => { window.fixture.mode = 'old'; });
    await click('Delete evaluation case', card('Backend two'));
    await dialog().getByRole('alert').filter({ hasText: /matching desktop|配套的桌面端/ }).waitFor();
    assert(await (await button('Confirm deletion', dialog())).isDisabled());
    await click('Keep data', dialog()); await gone();
    await page.evaluate(() => { window.fixture.mode = ''; });
    await click('Run snapshots'); await page.getByText('Original source snapshot', { exact: false }).waitFor();
    assert.equal(await page.evaluate(() => window.fixture.snapshots[0].members.length), 2);

    await page.getByRole('button', { name: 'Show experiments', exact: true }).click();
    await click('Delete experiment', card('Running backend'));
    await dialog().getByRole('alert').waitFor();
    assert(await (await button('Confirm deletion', dialog())).isDisabled());
    await click('Keep data', dialog()); await gone();
    await click('Results', card('Completed backend'));
    await (await button('Delete comparison group')).first().click();
    await dialog().getByText(/no-context baseline|无知识库基线组/).waitFor();
    await page.screenshot({ path: resolve(output, `${locale}-group-confirm.png`), fullPage: true });
    await click('Confirm deletion', dialog()); await gone();
    await page.waitForFunction(() => document.querySelectorAll('.workbench-results tbody tr').length === 2);
    await page.locator('.workbench-results .deletion-cohort-note').waitFor();
    assert.equal(await page.evaluate(() => new Set(window.fixture.snapshot.runs.map((run) => run.repeat)).size), 1);
    await (await button('Details')).first().click();
    await page.locator('dialog.workbench-dialog[open]').waitFor();
    await click('Delete comparison group', page.locator('dialog.workbench-dialog[open]'));
    assert.equal(await page.locator('dialog[open]').count(), 2, 'Nested confirmation stays in the native top layer');
    await click('Confirm deletion', dialog()); await gone();
    await page.locator('dialog.workbench-dialog[open]').waitFor({ state: 'hidden' });
    assert.equal(await page.evaluate(() => window.fixture.snapshot.runs.length), 0);
    await page.getByRole('button', { name: 'Show library', exact: true }).click();
    await page.getByRole('button', { name: 'Show experiments', exact: true }).click();
    await click('Delete experiment', card('Completed backend')); await click('Confirm deletion', dialog()); await gone();
    await card('Completed backend').waitFor({ state: 'hidden' });
    assert.equal(await page.evaluate(() => window.fixture.snapshot.experiments.length), 1);
    assert.equal(await page.evaluate(() => window.fixture.snapshots.length), 1);
    assert.deepEqual(errors, []);
    console.log(`${locale}: case/set/whole experiment/group deletion, snapshots, loading, cancellation, focus, stale preview, busy guards, old service and nested dialogs passed`);
    await page.close();
  }
} finally { await browser?.close(); await server.close(); }
