/** Step navigation UI regression. All service/native calls are fixtures. */
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { createServer } from 'vite';

const { chromium } = createRequire(import.meta.url)('playwright');
const server = await createServer({ server: { host: '127.0.0.1', port: 43187, strictPort: true }, logLevel: 'error' });
await server.listen();
let browser;
try {
  browser = await chromium.launch({ headless: true, ...(process.env.CTXBENCH_BROWSER_CHANNEL ? { channel: process.env.CTXBENCH_BROWSER_CHANNEL } : {}) });
  for (const locale of ['en', 'zh-CN']) {
    const page = await browser.newPage({ viewport: { width: 1100, height: 760 } });
    page.setDefaultTimeout(10000);
    const errors = []; page.on('pageerror', (error) => errors.push(error.message));
    await page.route('**/worker/**', (route) => route.abort());
    await page.addInitScript(() => {
      localStorage.setItem('ctxbench-distribution', 'Ubuntu');
      window.fixture = { calls: [] };
      const readText = File.prototype.text;
      File.prototype.text = function (...args) { return window.fixture.failRead ? Promise.reject(Error('Fixture read error')) : readText.apply(this, args); };
      window.__TAURI_INTERNALS__ = { invoke: async (command, args) => {
        window.fixture.calls.push({ command, args });
        if (command === 'list_local_images') return { images: ['fixture/test:v1'], error: null };
        if (command === 'worker_request' && args.path === '/intranet/profiles') return [];
        if (command === 'worker_request' && args.path === '/library/cases' && args.method === 'POST') {
          window.fixture.saved = args.body; return { id: 'case-fixture' };
        }
        throw Error('Unexpected fixture request: ' + command);
      } };
    });
    await page.route('**/__step_fixture__*', async (route) => {
      if (!route.request().isNavigationRequest()) return route.continue();
      const html = await server.transformIndexHtml('/__step_fixture__', `<!doctype html><html><head><meta charset="UTF-8" /></head><body><main id="root"></main><script type="module">
        import React from 'react'; import {createRoot} from 'react-dom/client';
        import {CaseEditor} from '/src/components/CaseEditor.tsx';
        import {I18nContext} from '/src/i18n.context.ts'; import {translate} from '/src/i18n.tsx'; import '/src/styles.css'; import '/src/ux.css';
        const locale = new URLSearchParams(location.search).get('locale'); window.uiT = key => translate(locale,key);
        createRoot(document.getElementById('root')).render(React.createElement(I18nContext.Provider,{value:{locale,setLocale:()=>{},t:(key,values)=>translate(locale,key,values)}},
          React.createElement(CaseEditor,{onClose:()=>{},onSaved:()=>{}})));
      </script></body></html>`);
      await route.fulfill({ contentType: 'text/html', body: html });
    });
    await page.goto(`http://127.0.0.1:43187/__step_fixture__?locale=${locale}`);
    const dialog = page.getByRole('dialog'); await dialog.waitFor();
    const t = key => page.evaluate(key => window.uiT(key), key);
    // A remounted controlled textarea may include its text in the implicit label.
    const field = async key => dialog.getByRole('textbox', { name: new RegExp('^' + (await t(key)).replace(/[.*+?^${}()|[\]\\]/g, '\\$&')) });
    const click = async key => dialog.getByRole('button', { name: await t(key), exact: true }).click();
    const focusedHeading = async key => {
      const heading = dialog.getByRole('heading', { name: await t(key), exact: true }); await heading.waitFor();
      await page.waitForFunction(node => node === document.activeElement, await heading.elementHandle());
      assert(await heading.evaluate(node => {
        const box = node.getBoundingClientRect(), form = node.closest('.workbench-form').getBoundingClientRect();
        return box.top >= form.top && box.bottom <= form.bottom && box.top - form.top < 50;
      }), 'New step heading must be at the visible top of the modal scroller');
    };
    assert(await dialog.evaluate(node => node.contains(document.activeElement)), 'Opening keeps focus in the existing modal');
    // Existing Modal opens with its close button focused; navigation must not steal it.
    await page.keyboard.press('Tab');
    assert(await (await field('Case name')).evaluate(node => node === document.activeElement), 'Initial keyboard path reaches the case name');
    await (await field('Case name')).fill('Scroll fixture');
    await (await field('Repository URL / worker path')).fill('https://git.example/backend');
    await (await field('Baseline commit (40 characters)')).fill('a'.repeat(40));
    await (await field('Test image reference')).fill('fixture/test:v1');
    const scroller = dialog.locator(':scope > .workbench-form');
    await scroller.evaluate(node => { node.scrollTop = node.scrollHeight; });
    assert(await scroller.evaluate(node => node.scrollTop > 100));
    await click('Next'); await focusedHeading('Task and tests');
    await page.keyboard.press('Tab');
    assert(await (await field('Task ID')).evaluate(node => node === document.activeElement), 'Tab enters the new step fields');
    await (await field('Task ID')).fill('focus-task');
    await (await field('Test command')).fill('node --test');
    assert(await scroller.evaluate(node => node.scrollTop > 0), 'Editing a lower field must not jump back to the title');
    await click('Next'); await focusedHeading('Review and save');
    await click('Save evaluation case');
    await dialog.getByRole('alert').waitFor();
    assert.equal(await page.evaluate(() => !!window.fixture.saved), false, 'Incomplete definitions must not be submitted');
    assert.equal(await dialog.locator('[aria-pressed="true"]').innerText(), '3. ' + await t('Review and save'), 'Validation does not silently change steps');
    await dialog.getByRole('button', { name: '2. ' + await t('Task and tests'), exact: true }).click();
    await focusedHeading('Task and tests');
    assert.equal(await (await field('Task ID')).inputValue(), 'focus-task');
    await (await field('Task prompt · agent-visible')).fill('Fix the specified behavior.');
    await dialog.getByText(await t('Hidden tests and reference fix (optional)'), { exact: true }).click();
    const patchText = await field('Hidden test patch');
    await patchText.fill('Manually written evaluator patch');
    const patchImport = dialog.locator('.patch-file-import').filter({ has: page.getByRole('button', { name: await t('Upload hidden test patch'), exact: true }) });
    const patchInput = patchImport.locator('input[type="file"]');
    assert(await patchInput.isHidden());
    assert.equal(await patchImport.getByRole('status').innerText(), await t('Patch text is present in the editor. It may be imported or edited; the current text is what will be saved.'));
    const selection = page.waitForEvent('filechooser');
    await patchImport.getByRole('button').click();
    await (await selection).setFiles({ name: 'hidden.patch', mimeType: 'text/plain', buffer: Buffer.from('Imported evaluator patch') });
    await page.waitForFunction(node => node.value === 'Imported evaluator patch', await patchText.elementHandle());
    await patchInput.setInputFiles([]);
    assert.equal(await patchText.inputValue(), 'Imported evaluator patch');
    await page.evaluate(() => { window.fixture.failRead = true; });
    await patchInput.setInputFiles({ name: 'other.patch', mimeType: 'text/plain', buffer: Buffer.from('Must not replace') });
    await dialog.getByRole('alert').waitFor();
    assert.equal(await patchText.inputValue(), 'Imported evaluator patch', 'Failed import preserves existing patch');
    await page.evaluate(() => { window.fixture.failRead = false; });
    await patchInput.setInputFiles({ name: 'hidden.patch', mimeType: 'text/plain', buffer: Buffer.from('Reimported same filename') });
    await page.waitForFunction(node => node.value === 'Reimported same filename', await patchText.elementHandle());
    await patchText.fill('Operator edited final evaluator patch');
    await dialog.getByRole('button', { name: '1. ' + await t('Repository and environment'), exact: true }).click();
    await focusedHeading('Repository and environment');
    assert.equal(await (await field('Repository URL / worker path')).inputValue(), 'https://git.example/backend');
    await click('Next'); await focusedHeading('Task and tests');
    assert.equal(await (await field('Task prompt · agent-visible')).inputValue(), 'Fix the specified behavior.');
    await click('Next'); await focusedHeading('Review and save');
    await click('Save evaluation case'); await page.waitForFunction(() => !!window.fixture.saved);
    assert.equal(await page.evaluate(() => window.fixture.saved.row.test.hiddenPatch), 'Operator edited final evaluator patch');
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ locale, forwardAndBackwardFocus: true, keyboardFields: true, ordinaryScroll: true, validationAndValuesPreserved: true, patchImportCancelFailureAndManualEdits: true, realServiceCalls: 0 }));
    await page.close();
  }
} finally { await browser?.close(); await server.close(); }
