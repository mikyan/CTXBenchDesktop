/** Completed-run log recovery and evidence sizing. Every service call is a read-only fixture. */
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { mkdir } from 'node:fs/promises';
import { resolve } from 'node:path';
import { createServer } from 'vite';

const { chromium } = createRequire(import.meta.url)('playwright');
const server = await createServer({ server: { host: '127.0.0.1', port: 43189, strictPort: true }, logLevel: 'error' });
await server.listen();
let browser;
try {
  browser = await chromium.launch({ headless: true, ...(process.env.CTXBENCH_BROWSER_CHANNEL ? { channel: process.env.CTXBENCH_BROWSER_CHANNEL } : {}) });
  for (const locale of ['en', 'zh-CN']) {
    const page = await browser.newPage({ viewport: { width: 1100, height: 850 } });
    page.setDefaultTimeout(15000);
    const errors = []; page.on('pageerror', cause => errors.push(cause.message));
    await page.route('**/worker/**', route => route.abort());
    await page.addInitScript(() => {
      const run = { id: 'exp-fixture:backend.v2:1:none', taskId: 'backend.v2', arm: 'none', repeat: 1, status: 'completed', testsPassed: true, solverRunId: 'solve-fixture', mock: false, updatedAt: '2026-09-11T00:00:00Z' };
      const session = { id: '1'.repeat(32), mode: 'solve', sequence: 1, startedAt: run.updatedAt, updatedAt: run.updatedAt, state: 'ended', exitCode: 0, startOffset: 0, endOffset: 25, truncated: false };
      window.fixture = { calls: [], run, rejected: true };
      window.__TAURI_INTERNALS__ = { invoke: async (command, args) => {
        window.fixture.calls.push({ command, ...args });
        if (command !== 'worker_request' || args.method !== 'GET') throw Error('Only read-only fixture requests are allowed');
        const url = new URL(args.path, 'http://fixture');
        if (url.pathname === '/run-record') return run;
        if (url.pathname === '/container-logs') {
          if (url.searchParams.get('benchmarkRunId') !== run.id) throw Error('Wrong run scope');
          if (window.fixture.rejected) throw Error('Select a valid experiment, preparation or run to view container logs.');
          return { sessions: [session], nextBefore: null };
        }
        if (url.pathname === '/container-logs/' + session.id) return { ...session, content: 'COMPLETED ARCHIVED OUTPUT\n', nextOffset: 25, hasMore: false, reset: true, pageOffset: 0 };
        if (url.pathname === '/run-output' && url.searchParams.get('file') === 'grading/evaluator.log') return { content: 'TAP version 13\n' + 'ok fixture assertion\n'.repeat(180) + 'FINAL_EVIDENCE_LINE\n', nextOffset: 4000, hasMore: false };
        throw Error('Unexpected fixture path ' + url.pathname);
      } };
    });
    await page.route('**/__run_evidence__*', async route => {
      if (!route.request().isNavigationRequest()) return route.continue();
      const html = await server.transformIndexHtml('/__run_evidence__', `<!doctype html><html><head><meta charset="UTF-8" /></head><body><main id="root"></main><script type="module">
        import React from 'react'; import {createRoot} from 'react-dom/client'; import {RunDialog} from '/src/components/WorkbenchDialogs.tsx';
        import {I18nContext} from '/src/i18n.context.ts'; import {translate} from '/src/i18n.tsx'; import '/src/styles.css'; import '/src/ux.css';
        const locale=new URLSearchParams(location.search).get('locale'); window.uiT=key=>translate(locale,key);
        createRoot(document.getElementById('root')).render(React.createElement(I18nContext.Provider,{value:{locale,setLocale:()=>{},t:(key,values)=>translate(locale,key,values)}},React.createElement(RunDialog,{run:window.fixture.run,onClose:()=>{}})));
      </script></body></html>`);
      await route.fulfill({ contentType: 'text/html', body: html });
    });
    await page.goto(`http://127.0.0.1:43189/__run_evidence__?locale=${locale}`, { timeout: 30000 });
    const t = key => page.evaluate(key => window.uiT(key), key);
    const dialog = page.getByRole('dialog'); const logs = dialog.locator('.container-log-viewer');
    await logs.getByRole('alert').filter({ hasText: await t('The evaluation service rejected this log request. Update matching service images, then refresh these logs. Saved evidence remains available; task execution is unchanged.') }).waitFor();
    const before = await page.evaluate(() => window.fixture.calls.length);
    await page.waitForTimeout(1250);
    assert.equal(await page.evaluate(() => window.fixture.calls.length), before, 'Do not repeatedly retry deterministic scope rejection');
    await dialog.getByRole('combobox', { name: await t('Evidence file'), exact: true }).selectOption('grading/evaluator.log');
    const evidence = dialog.getByRole('region', { name: await t('Saved evidence contents'), exact: true });
    await page.waitForFunction(node => node.textContent.includes('FINAL_EVIDENCE_LINE'), await evidence.elementHandle());
    for (const height of [850, 600]) {
      await page.setViewportSize({ width: 1100, height });
      await evidence.scrollIntoViewIfNeeded();
      const box = await evidence.evaluate(node => ({ height: node.getBoundingClientRect().height, client: node.clientHeight, scroll: node.scrollHeight, overflow: getComputedStyle(node).overflowY, shrink: getComputedStyle(node).flexShrink }));
      assert(box.height >= Math.min(240, height * .4), 'Evidence must not collapse to one line in the flex modal');
      assert(box.height <= height * .5 + 1, 'Evidence remains bounded on smaller displays');
      assert(box.scroll > box.client); assert.equal(box.overflow, 'auto'); assert.equal(box.shrink, '0');
      await evidence.focus(); await evidence.press('End');
      await page.waitForFunction(node => node.scrollTop > 0, await evidence.elementHandle());
    }
    await page.setViewportSize({ width: 1100, height: 850 });
    await evidence.evaluate(node => { node.scrollTop = 0; }); await evidence.scrollIntoViewIfNeeded();
    await mkdir(resolve('artifacts/ux-feedback-headless'), { recursive: true });
    await page.screenshot({ path: resolve(`artifacts/ux-feedback-headless/evidence-${locale}.png`) });
    await page.evaluate(() => { window.fixture.rejected = false; });
    await logs.getByRole('button', { name: await t('Refresh logs now'), exact: true }).click();
    await page.waitForFunction(() => document.querySelector('.live-container-output').textContent.includes('COMPLETED ARCHIVED OUTPUT'));
    await logs.getByRole('alert').waitFor({ state: 'detached' });
    assert.equal(await logs.getByRole('combobox').locator('option').count(), 2);
    assert((await logs.getByRole('status').innerText()).includes(await t('Log stream ended')));
    assert((await evidence.innerText()).includes('FINAL_EVIDENCE_LINE'), 'Log recovery preserves independent saved evidence');
    assert.deepEqual(errors, []);
    assert(await page.evaluate(() => window.fixture.calls.every(call => call.command === 'worker_request' && call.method === 'GET')));
    console.log(JSON.stringify({ locale, compoundRunScope: true, rejectionStopsPolling: true, completedLogRecovery: true, evidenceMinimumHeightAndKeyboardScroll: true, realServiceCalls: 0 }));
    await page.close();
  }
} finally { await browser?.close(); await server.close(); }
