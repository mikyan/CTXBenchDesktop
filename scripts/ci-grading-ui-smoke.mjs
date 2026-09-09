/** Isolated UI fixtures only: no GitHub writes, model calls or credential persistence. */
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { mkdir } from 'node:fs/promises';
import { resolve } from 'node:path';
import { createServer } from 'vite';
const { chromium } = createRequire(import.meta.url)('playwright');
const server = await createServer({ server: { host: '127.0.0.1', port: 43178, strictPort: true }, logLevel: 'error' });
await server.listen(); let browser;
try {
  browser = await chromium.launch({ headless: true, ...(process.env.CTXBENCH_BROWSER_CHANNEL ? { channel: process.env.CTXBENCH_BROWSER_CHANNEL } : {}) });
  for (const locale of ['en', 'zh-CN']) {
    const page = await browser.newPage({ viewport: { width: 1180, height: 860 } }); page.setDefaultTimeout(10000);
    const errors = []; page.on('pageerror', (error) => errors.push(error.message));
    await page.route('**/worker/**', (route) => route.abort());
    await page.addInitScript(() => {
      localStorage.setItem('ctxbench-distribution', 'Ubuntu');
      window.fixture = { calls: [], connections: [], saved: null };
      window.__TAURI_INTERNALS__ = { invoke: async (command, args) => {
        if (command === 'list_local_images') return { images: ['company/java:17'] };
        if (command !== 'worker_request') throw Error('Unexpected native command');
        const { path, method, body } = args;
        // Never even store the fake token in the fixture's call log.
        window.fixture.calls.push({ path, method, body: path.endsWith('/credential') ? undefined : structuredClone(body) });
        if (path === '/ci/connections' && method === 'GET') return structuredClone(window.fixture.connections);
        if (path === '/ci/connections' && method === 'POST') { const row = { id: 'a'.repeat(64), document: body, credentialConfigured: false }; window.fixture.connections.push(row); return row; }
        if (path.endsWith('/credential')) { window.fixture.connections[0].credentialConfigured = Boolean(body.token); return { credentialConfigured: Boolean(body.token) }; }
        if (path === '/library/cases' && method === 'POST') { window.fixture.saved = body; return { id: 'case-ci' }; }
        if (path === '/library/cases/case-ci') return { id: 'case-ci', ...window.fixture.saved, revision: 1, usedBy: [] };
        if (path === '/intranet/profiles') return [];
        throw Error('Unexpected fixture path: ' + path);
      } };
    });
    await page.route('**/__ci_fixture__*', async (route) => {
      if (!route.request().isNavigationRequest()) return route.continue();
      const html = await server.transformIndexHtml('/__ci_fixture__', `<!doctype html><html><head><meta charset="UTF-8" /></head><body><main id="root"></main><script type="module">
        import React,{useState} from 'react'; import {createRoot} from 'react-dom/client';
        import {CaseEditor} from '/src/components/CaseEditor.tsx'; import {CIGradingResult} from '/src/components/CIGradingResult.tsx';
        import {I18nContext} from '/src/i18n.context.ts'; import {translate} from '/src/i18n.tsx'; import '/src/styles.css'; import '/src/ux.css';
        const locale = new URLSearchParams(location.search).get('locale'); window.uiT = (key)=>translate(locale,key);
        function Fixture(){const [open,setOpen]=useState(true); const [edit,setEdit]=useState(false); return React.createElement(React.Fragment,null,
          React.createElement('button',{onClick:()=>{setEdit(true);setOpen(true);}},'Reopen'),
          open&&React.createElement(CaseEditor,{caseId:edit?'case-ci':undefined,onSaved:()=>{},onClose:()=>setOpen(false)}),
          React.createElement(CIGradingResult,{run:{grade:{gradingMode:'ci',ci:{provider:'github-actions',status:'completed',repository:'team/backend',remoteId:123,branch:'ctxbench-eval/example',commit:'b'.repeat(40)},requiredJobs:[{name:'test',conclusion:'success'}],testCounts:{total:12,passed:12,failures:0,errors:0,skipped:0}}}}));}
        createRoot(document.getElementById('root')).render(React.createElement(I18nContext.Provider,{value:{locale,setLocale:()=>{},t:(key,values)=>translate(locale,key,values)}},React.createElement(Fixture)));
      </script></body></html>`);
      await route.fulfill({ contentType: 'text/html', body: html });
    });
    await page.goto(`http://127.0.0.1:43178/__ci_fixture__?locale=${locale}`);
    const t = (key) => page.evaluate((value) => window.uiT(value), key);
    const field = async (key) => ['Choose an installed image', 'Grading method', 'CI platform connection'].includes(key)
      ? page.getByRole('combobox', { name: await t(key), exact: true }) : ['Required job names (one per line)', 'Task prompt · agent-visible'].includes(key)
        ? page.getByRole('textbox', { name: await t(key), exact: true }) : page.getByLabel(await t(key), { exact: true });
    const click = async (key) => page.getByRole('button', { name: await t(key), exact: true }).click();
    await (await field('Case name')).fill('Backend CI case');
    await (await field('Repository URL / worker path')).fill('https://github.com/team/backend.git');
    await (await field('Baseline commit (40 characters)')).fill('b'.repeat(40));
    await (await field('Choose an installed image')).selectOption('company/java:17');
    await click('Next'); await (await field('Task prompt · agent-visible')).fill('Fix the API response.');
    await (await field('Grading method')).selectOption('ci');
    await page.getByText(await t('Add platform connection / new version'), { exact: true }).click();
    await (await field('Connection name')).fill('Personal GitHub'); await (await field('CI repository (owner/name)')).fill('team/backend');
    await click('Save connection version');
    await page.getByText(await t('Connection saved. No code was uploaded and no workflow was triggered.'), { exact: true }).waitFor();
    await page.locator('summary').filter({ hasText: await t('Platform token (evaluation service only)') }).click();
    await (await field('CI access token')).fill('UI_SYNTHETIC_CI_TOKEN'); await click('Set platform token');
    await page.getByText(await t('Platform token configured for this session.'), { exact: true }).waitFor();
    assert.equal(await (await field('CI access token')).inputValue(), '');
    await (await field('Required job names (one per line)')).fill('build\ntest\n');
    await (await field('JUnit report artifact name (optional)')).fill('test-results');
    await (await field('Minimum executed tests')).fill('10');
    await click('Next'); await click('Save evaluation case');
    await page.getByRole('alert').filter({ hasText: await t('CI: acknowledge uploading candidate code and triggering remote workflows.') }).waitFor();
    assert.equal(await page.evaluate(() => window.fixture.saved), null);
    await page.getByRole('button', { name: '2. ' + await t('Task and tests'), exact: true }).click();
    await page.getByRole('checkbox', { name: await t('I authorize uploading candidate code and running CI on this platform, which may consume CI quota. I have checked repository visibility, secrets, runners and deployment triggers.'), exact: true }).check();
    await mkdir('artifacts/ci-ui', { recursive: true });
    await page.screenshot({ path: resolve(`artifacts/ci-ui/${locale}-ci-editor.png`) });
    await click('Next'); assert.equal(await page.getByRole('button', { name: await t('Run self-test (no model tokens)'), exact: true }).count(), 0);
    await click('Save evaluation case'); await page.waitForFunction(() => window.fixture.saved);
    const saved = await page.evaluate(() => window.fixture.saved);
    assert.deepEqual(saved.row.test.ci.requiredJobs, ['build', 'test']); assert.equal(saved.row.test.ci.minTests, 10);
    assert.equal(saved.row.test.command, undefined); assert(!JSON.stringify(saved).includes('UI_SYNTHETIC_CI_TOKEN'));
    await page.getByRole('button', { name: 'Reopen', exact: true }).click(); await click('Next');
    assert.equal(await (await field('Grading method')).inputValue(), 'ci'); assert.equal(await (await field('Required job names (one per line)')).inputValue(), 'build\ntest');
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ locale, passed: true, createsAndEditsCI: true, explicitConsent: true, separateCredential: true, noRemoteCalls: true }));
    await page.close();
  }
} finally { await browser?.close(); await server.close(); }
