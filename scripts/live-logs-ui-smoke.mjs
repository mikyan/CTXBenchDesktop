/** Read-only bilingual live-console interaction test; no Docker or provider calls. */
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { mkdir } from 'node:fs/promises';
import { resolve } from 'node:path';
import { createServer } from 'vite';

const { chromium } = createRequire(import.meta.url)('playwright');
const server = await createServer({ server: { host: '127.0.0.1', port: 43179, strictPort: true }, logLevel: 'error' });
await server.listen();
let browser;
try {
  browser = await chromium.launch({ headless: true, ...(process.env.CTXBENCH_BROWSER_CHANNEL ? { channel: process.env.CTXBENCH_BROWSER_CHANNEL } : {}) });
  for (const locale of ['en', 'zh-CN']) {
    const page = await browser.newPage({ viewport: { width: 1100, height: 850 } });
    page.setDefaultTimeout(15000);
    const errors = []; page.on('pageerror', (error) => errors.push(error.message));
    await page.addInitScript(() => {
      window.fixture = { calls: [], sessions: [], texts: {}, fail: false, legacy: false, reset: false, export: null };
      window.__TAURI_INTERNALS__ = { invoke: async (command, args) => {
        const fixture = window.fixture;
        fixture.calls.push({ command, ...args });
        if (command === 'save_export') { fixture.export = args; return 'fixture.txt'; }
        if (command !== 'worker_request') throw Error('Unexpected native call');
        if (args.method !== 'GET') throw Error('Log viewing must be read-only');
        if (fixture.legacy) throw Error('Not Found');
        if (fixture.fail) throw Error('synthetic connection failure');
        const url = new URL(args.path, 'http://fixture');
        if (url.pathname === '/container-logs') {
          const before = Number(url.searchParams.get('before') ?? Infinity);
          const sessions = fixture.sessions.filter((item) => item.sequence < before).slice(0, 200);
          return { sessions, nextBefore: sessions.length === 200 ? sessions.at(-1).sequence : null };
        }
        const session = fixture.sessions.find((item) => item.id === url.pathname.split('/').at(-1));
        if (!session) throw Error('Record not found');
        const full = fixture.texts[session.id];
        const offset = fixture.reset ? 0 : Number(url.searchParams.get('offset') ?? Math.max(0, full.length - 64000));
        const next = Math.min(full.length, offset + 64000);
        return { ...session, content: full.slice(offset, next), pageOffset: offset, nextOffset: next, hasMore: next < full.length, reset: fixture.reset, endOffset: full.length };
      } };
      window.addLog = (id, mode, text) => {
        window.fixture.sessions.unshift({ id, mode, sequence: window.fixture.sessions.length + 1, state: 'streaming', exitCode: null, startedAt: '2026-09-09T06:00:00Z', updatedAt: '2026-09-09T06:00:01Z', startOffset: 0, endOffset: text.length, truncated: false });
        window.fixture.texts[id] = text;
      };
    });
    await page.route('**/__live_log_fixture__*', async (route) => {
      if (!route.request().isNavigationRequest()) return route.continue();
      const html = await server.transformIndexHtml('/__live_log_fixture__', `<!doctype html><html><head><meta charset="UTF-8" /></head><body><div id="root"></div><script type="module">
        import React from 'react'; import {createRoot} from 'react-dom/client';
        import {ContainerLogViewer} from '/src/components/ContainerLogs.tsx';
        import {I18nContext} from '/src/i18n.context.ts'; import {translate} from '/src/i18n.tsx'; import '/src/styles.css'; import '/src/ux.css';
        const locale = new URLSearchParams(location.search).get('locale'); window.uiT = (key) => translate(locale,key);
        const root=createRoot(document.getElementById('root')); window.unmountLogs=()=>root.unmount();
        root.render(React.createElement(I18nContext.Provider,{value:{locale,setLocale:()=>{},t:(key,values)=>translate(locale,key,values)}},React.createElement(ContainerLogViewer,{scope:{experimentId:'experiment-one'}})));
      </script></body></html>`);
      await route.fulfill({ contentType: 'text/html', body: html });
    });
    await page.goto(`http://127.0.0.1:43179/__live_log_fixture__?locale=${locale}`);
    const t = (key) => page.evaluate((value) => window.uiT(value), key);
    const button = async (key) => page.getByRole('button', { name: await t(key), exact: true });
    const click = async (key) => (await button(key)).click();
    const status = async (key) => page.getByRole('status').filter({ hasText: await t(key) }).waitFor();
    const output = page.locator('pre.live-container-output');
    await status('Waiting for a container to start. Cached work may not start a new container.');
    await page.evaluate(() => window.addLog('solver-one', 'solve', '启动中文🙂\nREADY [REDACTED]\n'));
    await page.waitForFunction(() => document.querySelector('pre').textContent.includes('READY'));
    await status('Live · checking for new output every second');
    await page.evaluate(() => { window.fixture.texts['solver-one'] += 'building…\n'; });
    await page.waitForFunction(() => document.querySelector('pre').textContent.includes('building…'));
    assert.equal((await output.innerText()).split('READY').length, 2, 'Cursor append must not duplicate previous output');
    await click('Pause log refresh');
    await status('Log refresh paused; the task keeps running.');
    const pausedCount = await page.evaluate(() => window.fixture.calls.length);
    await page.evaluate(() => { window.fixture.texts['solver-one'] += 'while paused\n'; });
    await page.waitForTimeout(1250);
    assert.equal(await page.evaluate(() => window.fixture.calls.length), pausedCount);
    assert(!(await output.innerText()).includes('while paused'));
    await click('Refresh logs now');
    await page.waitForFunction(() => document.querySelector('pre').textContent.includes('while paused'));
    const refreshedCount = await page.evaluate(() => window.fixture.calls.length);
    await page.waitForTimeout(1250);
    assert.equal(await page.evaluate(() => window.fixture.calls.length), refreshedCount);
    await click('Resume log refresh');
    await page.evaluate(() => window.addLog('test-one', 'test', 'TEST NEW STAGE\n'));
    await page.waitForFunction(() => document.querySelector('pre').textContent.includes('TEST NEW STAGE'));
    assert(!(await output.innerText()).includes('READY'), 'New container must not inherit another stream');
    await page.getByRole('combobox', { name: await t('Container / stage') }).selectOption('solver-one');
    await page.waitForFunction(() => document.querySelector('pre').textContent.includes('READY'));
    await page.evaluate(() => { window.fixture.fail = true; });
    await page.getByRole('alert').filter({ hasText: await t('Log connection lost; reconnecting. The task is not paused.') }).waitFor();
    assert((await output.innerText()).includes('READY'), 'Disconnect must preserve visible output');
    await page.evaluate(() => { window.fixture.fail = false; window.fixture.texts['solver-one'] += 'RECONNECTED\n'; });
    await page.waitForFunction(() => document.querySelector('pre').textContent.includes('RECONNECTED'));
    await page.getByRole('alert').waitFor({ state: 'hidden' });
    await page.evaluate(() => { window.fixture.reset = true; window.fixture.texts['solver-one'] = 'ROTATED TAIL\n'; });
    await page.waitForFunction(() => document.querySelector('pre').textContent === 'ROTATED TAIL\n');
    await page.evaluate(() => { window.fixture.reset = false; const session = window.fixture.sessions.find((item) => item.id === 'solver-one'); session.state = 'ended'; session.exitCode = 7; });
    await status('Log stream ended');
    assert((await page.getByRole('status').innerText()).includes('7'));
    await click('Export visible logs');
    assert.equal(await page.evaluate(() => window.fixture.export.content), 'ROTATED TAIL\n');
    await page.getByRole('checkbox', { name: await t('Auto-scroll logs') }).uncheck();
    assert(!(await page.getByRole('checkbox', { name: await t('Auto-scroll logs') }).isChecked()));
    assert.equal(await page.locator('.checkbox-line').evaluate((element) => getComputedStyle(element).flexDirection), 'row', 'Shared form styles must not stack the log toggle vertically');
    await page.getByText(await t('Log limits and debugging tips'), { exact: true }).click();
    assert(await page.locator('details').evaluate((node) => node.open));
    // Preparation failures have no Docker container. Read every saved character,
    // including the beginning of an archive larger than the old retention limit.
    await page.evaluate(() => {
      for (const item of window.fixture.sessions) item.state = 'ended';
      window.addLog('pre-agent-failure', 'preparation', 'FIRST_BUILD_ERROR\n' + 'diagnostic line\n'.repeat(82000) + 'LAST_BUILD_ERROR\n');
      Object.assign(window.fixture.sessions[0], { source: 'service', label: 'Prepare queued operation', state: 'ended',
        failure: { logSessionId: 'pre-agent-failure', failedAt: '2026-09-09T06:30:00Z', stage: 'Fetch frozen Git baseline', agentStarted: false,
          summary: 'fatal: fixture repository access denied', hint: 'Check repository access, the frozen baseline commit and the working directory permissions.' } });
    });
    await page.getByRole('combobox', { name: await t('Container / stage') }).selectOption('');
    await page.waitForFunction(() => document.querySelector('.live-container-output').textContent.includes('LAST_BUILD_ERROR'));
    await page.getByText(await t('No Agent container start was recorded for this attempt.'), { exact: true }).waitFor();
    assert(!(await output.innerText()).includes('FIRST_BUILD_ERROR'));
    await click('Read complete log from beginning');
    await page.waitForFunction(() => document.querySelector('.live-container-output').textContent.includes('FIRST_BUILD_ERROR'));
    await status('Browsing saved log pages; task execution continues independently.');
    assert(await (await button('Previous log page')).isDisabled());
    const parts = [await output.innerText()];
    while (await (await button('Next log page')).isEnabled()) {
      const count = parts.length;
      await click('Next log page');
      await page.waitForFunction((offset) => document.querySelector('.container-log-viewer').textContent.includes(': ' + offset), count * 64000);
      parts.push(await output.innerText());
    }
    assert.equal(parts.join(''), await page.evaluate(() => window.fixture.texts['pre-agent-failure']), 'Every archived character must be readable, not just the last megabyte');
    await click('Previous log page');
    await page.waitForFunction(() => !document.querySelector('.live-container-output').textContent.includes('LAST_BUILD_ERROR'));
    await click('Return to live tail');
    await page.waitForFunction(() => document.querySelector('.live-container-output').textContent.includes('LAST_BUILD_ERROR'));
    await mkdir(resolve('artifacts/live-logs-ui'), { recursive: true });
    await page.screenshot({ path: resolve(`artifacts/live-logs-ui/${locale}.png`), fullPage: true });
    await page.evaluate(() => {
      window.addLog('retry', 'preparation', 'NEW ATTEMPT\n');
      window.fixture.sessions[0].startedAt = '2026-09-09T07:00:00Z';
    });
    await page.getByRole('combobox', { name: await t('Container / stage') }).selectOption('');
    await page.waitForFunction(() => document.querySelector('.live-container-output').textContent.includes('NEW ATTEMPT'));
    await page.locator('.failure-details').waitFor({ state: 'hidden' });
    await page.evaluate(() => { window.fixture.sessions[0].state = 'ended'; });
    await click('Refresh logs now');
    await status('Log stream ended');
    assert((await output.innerText()).includes('NEW ATTEMPT'), 'A successful retry must not automatically select its old failure');
    // A fresh mount resets the inventory paging cursor; scope stays read-only.
    await page.reload();
    await page.evaluate(() => { for (let index = 0; index < 205; index++) window.addLog('history-' + index, 'test', 'HISTORY ' + index + '\n'); });
    await click('Refresh logs now');
    await click('Load older log sources');
    await page.getByRole('combobox', { name: await t('Container / stage') }).selectOption('history-0');
    await page.waitForFunction(() => document.querySelector('.live-container-output').textContent === 'HISTORY 0\n');
    await page.evaluate(() => { window.fixture.legacy = true; });
    await click('Refresh logs now');
    await page.getByRole('alert').filter({ hasText: await t('Live container logs require updated evaluation service images. Existing evidence files remain available.') }).waitFor();
    const stoppedCount = await page.evaluate(() => window.fixture.calls.length);
    await page.waitForTimeout(1250);
    assert.equal(await page.evaluate(() => window.fixture.calls.length), stoppedCount, 'Unsupported images should not be hammered');
    await page.evaluate(() => window.unmountLogs());
    await page.waitForTimeout(1250);
    assert.equal(await page.evaluate(() => window.fixture.calls.length), stoppedCount);
    assert.deepEqual(errors, []);
    assert(await page.evaluate(() => window.fixture.calls.filter((call) => call.command === 'worker_request').every((call) => call.method === 'GET')));
    await page.close();
    console.log(`${locale}: streaming, pause/resume, reconnect, pre-Agent failure, complete 1.2M archive paging, retry, older sources, export, legacy and teardown passed`);
  }
} finally {
  await browser?.close();
  await server.close();
}
