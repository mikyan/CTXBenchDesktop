/** Isolated headless UI regression: no native window, Docker, service or Provider calls. */
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { mkdir } from 'node:fs/promises';
import { resolve } from 'node:path';
import { createServer } from 'vite';

const { chromium } = createRequire(import.meta.url)('playwright');
const server = await createServer({ server: { host: '127.0.0.1', port: 43186, strictPort: true }, logLevel: 'error' });
await server.listen();
let browser;
try {
  browser = await chromium.launch({ headless: true, ...(process.env.CTXBENCH_BROWSER_CHANNEL ? { channel: process.env.CTXBENCH_BROWSER_CHANNEL } : {}) });
  const output = resolve('artifacts/ux-feedback-headless'); await mkdir(output, { recursive: true });
  for (const locale of ['en', 'zh-CN']) {
    const page = await browser.newPage({ viewport: { width: 1100, height: 820 } });
    page.setDefaultTimeout(15000);
    const errors = []; page.on('pageerror', (error) => errors.push(error.message));
    await page.route('**/worker/**', (route) => route.abort());
    await page.addInitScript(() => {
      window.fixture = { calls: [], fail: false, images: ['ctxbench/agent-pi:0.1.0', 'company/base:v1'] };
      window.__TAURI_INTERNALS__ = { invoke: async (command, args) => {
        window.fixture.calls.push({ command, args });
        if (command === 'desktop_connection') return { isolated: true, baseUrl: 'http://127.0.0.1:48174/v1' };
        if (command === 'list_local_images') {
          if (window.fixture.fail) throw Error('fixture inventory unavailable');
          return { images: window.fixture.images, error: null };
        }
        throw Error('Unexpected native request: ' + command);
      } };
    });
    await page.route('**/__ux_feedback__*', async (route) => {
      if (!route.request().isNavigationRequest()) return route.continue();
      const html = await server.transformIndexHtml('/__ux_feedback__', `<!doctype html><html><head><meta charset="UTF-8" /></head><body><main id="root"></main><script type="module">
        import React from 'react'; import {createRoot} from 'react-dom/client';
        import {Topbar} from '/src/components/Topbar.tsx'; import {ImageRecipeGuide} from '/src/components/ImageRecipeGuide.tsx';
        import {I18nContext} from '/src/i18n.context.ts'; import {translate} from '/src/i18n.tsx'; import '/src/styles.css'; import '/src/ux.css';
        const locale = new URLSearchParams(location.search).get('locale'); window.uiT = (key) => translate(locale,key);
        createRoot(document.getElementById('root')).render(React.createElement(I18nContext.Provider,{value:{locale,setLocale:()=>{},t:(key,values)=>translate(locale,key,values)}},
          React.createElement(React.Fragment,null,React.createElement(Topbar,{runtime:'desktop'}),React.createElement('div',{className:'workbench-form'},React.createElement(ImageRecipeGuide,{distribution:'Ubuntu',onApply:()=>{}})))));
      </script></body></html>`);
      await route.fulfill({ contentType: 'text/html', body: html });
    });
    await page.goto(`http://127.0.0.1:43186/__ux_feedback__?locale=${locale}`);
    const t = (key) => page.evaluate((key) => window.uiT(key), key);
    const click = async (key) => page.getByRole('button', { name: await t(key), exact: true }).click();
    const picker = page.getByLabel(await t('Choose an installed base image'));
    await picker.selectOption('ctxbench/agent-pi:0.1.0');
    const manual = page.getByLabel(await t('Local base image'), { exact: true });
    assert.equal(await manual.inputValue(), 'ctxbench/agent-pi:0.1.0');
    await manual.fill('manual/custom:v2');
    await page.evaluate(() => { window.fixture.fail = true; });
    await click('Refresh local images');
    await page.getByRole('alert').waitFor();
    assert.equal(await manual.inputValue(), 'manual/custom:v2', 'Failed discovery must not erase manual input');
    await page.evaluate(() => { window.fixture.fail = false; window.fixture.images = ['new/base:v3']; });
    await click('Refresh local images');
    await picker.selectOption('new/base:v3');
    assert.equal(await manual.inputValue(), 'new/base:v3');
    await click('Help');
    const dialog = page.getByRole('dialog', { name: await t('User guide · start with one case') });
    await dialog.waitFor();
    assert(await dialog.evaluate((node) => node.matches(':modal')), 'Help must open in the native top layer');
    assert.equal(page.context().pages().length, 1, 'Help must not open a browser tab');
    await page.screenshot({ path: resolve(output, `${locale}-help.png`), fullPage: true });
    await page.keyboard.press('Escape'); await dialog.waitFor({ state: 'hidden' });
    assert.equal(await manual.inputValue(), 'new/base:v3', 'Reading help must not reset the recipe');
    assert.deepEqual(errors, []);
    assert(await page.evaluate(() => window.fixture.calls.every(({ command }) => ['desktop_connection', 'list_local_images'].includes(command))));
    console.log(JSON.stringify({ locale, help: 'passed', localImageSelection: 'passed', failedRefreshRecovery: 'passed', realServiceCalls: 0 }));
    await page.close();
  }
} finally { await browser?.close(); await server.close(); }
