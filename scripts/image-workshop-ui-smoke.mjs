/** UI interaction fixtures, never a real model or Docker client. */
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { mkdir } from 'node:fs/promises';
import { resolve } from 'node:path';
import { createServer } from 'vite';
const { chromium } = createRequire(import.meta.url)('playwright');
const server = await createServer({ server: { host: '127.0.0.1', port: 43178, strictPort: true }, logLevel: 'error' });
await server.listen();
const browser = await chromium.launch({ headless: true, channel: process.env.CTXBENCH_BROWSER_CHANNEL || undefined });
try {
  for (const locale of ['en', 'zh-CN']) {
    const page = await browser.newPage({ viewport: { width: 1180, height: 900 } });
    page.setDefaultTimeout(12000);
    const errors = []; page.on('pageerror', (error) => errors.push(error.message));
    await page.route('**/worker/**', (route) => route.abort());
    await page.addInitScript(() => {
      window.calls = []; window.jobs = {}; window.pullFails = false;
      window.__TAURI_INTERNALS__ = { invoke: async (command, args) => {
        window.calls.push({ command, ...structuredClone(args) });
        if (command === 'list_local_images') return { images: ['company/base:v1'] };
        if (command !== 'worker_request') throw Error('Unexpected call');
        const { path, method, body } = args;
        if (path === '/intranet') return { profiles: [], adaptations: [], drafts: [], operations: [], transferDirectory: '/tmp/fixture' };
        const saved = window.savedCase && { ...window.savedCase.row, id: 'case-saved', name: window.savedCase.name, taskId: window.savedCase.row.id, benchmark: 'custom', revision: 1, customAgentImage: window.savedCase.row.agent.image };
        if (path === '/library') return { version: 1, sets: [], cases: saved ? [saved] : [] };
        if (path === '/library/selections/case-saved') return { dataset: { ...saved, count: 1 }, revision: 'rev-1', tasks: [{ ...saved, id: saved.taskId }] };
        if (path === '/runtime') return { credentials: [], projectEnvironmentVersion: 1 };
        if (path === '/token-budgets') return [{ id: 'exhausted', provider: 'mock', model: 'deterministic', remainingTokens: 0 }];
        if (path === '/intranet/profiles' || path === '/constraint-packages' || path.startsWith('/ci/selection/')) return [];
        if (path.includes('/project-image-sources')) return { overrides: [] };
        if (path === '/ci/connections') return [];
        if (path === '/library/cases' && method === 'POST') { window.savedCase = body; return { id: 'case-saved' }; }
        if (path.startsWith('/intranet/operations/') && method === 'POST') {
          if (window.pullFails) throw Error('Registry is unavailable.');
          const id = 'op-' + window.calls.length;
          const job = { id, kind: 'intranet:' + path.split('/').at(-1), status: 'completed', result: { tag: body.image || 'ctxbench/adapted:fixture', imageId: 'sha256:' + 'a'.repeat(64) }, progress: { log: 'Layers verified', percent: 100 } };
          window.jobs[id] = job; return job;
        }
        if (path.startsWith('/intranet/operations/')) return window.jobs[path.split('/').at(-1)];
        throw Error('Unexpected path ' + path);
      } };
    });
    await page.route('**/__image_workshop__*', async (route) => {
      if (!route.request().isNavigationRequest()) return route.continue();
      const body = await server.transformIndexHtml('/__image_workshop__', `<!doctype html><html><head><meta charset="UTF-8"></head><body><main id="root"></main><script type="module">
        import React,{useState} from 'react'; import {createRoot} from 'react-dom/client';
        import {IntranetWorkbench} from '/src/components/IntranetWorkbench.tsx'; import {CaseEditor} from '/src/components/CaseEditor.tsx';
        import {ExperimentComposer} from '/src/components/ExperimentComposer.tsx';
        import {I18nContext} from '/src/i18n.context.ts'; import {translate} from '/src/i18n.tsx'; import '/src/styles.css'; import '/src/ux.css';
        const locale=new URLSearchParams(location.search).get('locale'); window.uiT=(key)=>translate(locale,key);
        function Fixture(){const [editing,setEditing]=useState(false);const [experiment,setExperiment]=useState(false);return React.createElement('div',{className:'page'},
          React.createElement('button',{onClick:()=>setExperiment(true)},'Open experiment fixture'),
          React.createElement('button',{onClick:()=>setEditing(true)},'Open case fixture'),React.createElement(IntranetWorkbench,{section:'Image adaptation'}),
          editing&&React.createElement(CaseEditor,{onClose:()=>setEditing(false),onSaved:()=>{setEditing(false)}}),
          experiment&&React.createElement(ExperimentComposer,{creating:false,initialDataset:'case-saved',artifacts:[],onClose:()=>setExperiment(false),onCreate:async(request)=>{window.experiment=request;setExperiment(false)}}));}
        createRoot(document.getElementById('root')).render(React.createElement(I18nContext.Provider,{value:{locale,setLocale:()=>{},t:(key,values)=>translate(locale,key,values)}},React.createElement(Fixture)));
      </script></body></html>`);
      await route.fulfill({ contentType: 'text/html', body });
    });
    await page.goto(`http://127.0.0.1:43178/__image_workshop__?locale=${locale}`);
    const t = (key) => page.evaluate((key) => window.uiT(key), key);
    const pull = page.locator('.remote-image-pull').first();
    await pull.getByLabel(await t('Remote image reference'), { exact: true }).fill('registry.company.example/base:v1');
    assert(await pull.getByRole('button', { name: await t('Pull image'), exact: true }).isDisabled());
    await pull.getByRole('checkbox').check();
    await page.evaluate(() => { window.pullFails = true; });
    await pull.getByRole('button', { name: await t('Pull image'), exact: true }).click();
    await pull.getByRole('alert').waitFor();
    await page.evaluate(() => { window.pullFails = false; });
    await pull.getByRole('button', { name: await t('Pull image'), exact: true }).click();
    await pull.getByText('registry.company.example/base:v1', { exact: true }).waitFor();
    const guide = page.locator('.image-recipe-guide');
    await guide.getByLabel(await t('Adaptation name'), { exact: true }).fill('Company custom Agent');
    await guide.getByLabel(await t('Local base image'), { exact: true }).fill('registry.company.example/base:v1');
    await guide.getByRole('button', { name: await t('Next'), exact: true }).click();
    await guide.getByRole('combobox', { name: await t('Dependency command template'), exact: true }).selectOption('python');
    await guide.getByRole('button', { name: await t('Next'), exact: true }).click();
    await guide.getByLabel(await t('Non-secret configuration files'), { exact: true }).setInputFiles({ name: 'settings.json', mimeType: 'application/json', buffer: Buffer.from('{"mode":"batch"}') });
    await guide.getByRole('textbox', { name: await t('Image defaults (NAME=value, one per line)'), exact: true }).fill('HOME=/home/ctxbench\nMY_AGENT_CONFIG=/opt/company/settings.json');
    await guide.getByRole('button', { name: await t('Next'), exact: true }).click();
    assert((await guide.locator('pre').innerText()).includes('COPY ["settings.json","/opt/company/settings.json"]'));
    await guide.getByRole('button', { name: await t('Use recipe in the build form'), exact: true }).click();
    const build = page.getByRole('button', { name: await t('Build adapted image'), exact: true });
    assert(await build.isDisabled());
    await page.getByLabel(await t('I trust this recipe and base image. Build commands execute locally; I have checked that files and layers contain no credentials.'), { exact: true }).check();
    await build.click();
    await page.getByText('ctxbench/adapted:fixture', { exact: true }).waitFor();
    const request = await page.evaluate(() => window.calls.find((call) => call.path === '/intranet/operations/image-build').body);
    assert.equal(request.files[0].path, 'settings.json'); assert.equal(request.network, 'bridge');
    assert(request.dockerfile.includes('MY_AGENT_CONFIG')); assert(!request.dockerfile.includes('FROM '));
    await page.getByRole('button', { name: 'Open case fixture', exact: true }).click();
    const dialog = page.locator('dialog[open]');
    await dialog.getByLabel(await t('Case name'), { exact: true }).fill('My Agent case');
    await dialog.getByLabel(await t('Repository URL / worker path'), { exact: true }).fill('https://git.example/backend');
    await dialog.getByLabel(await t('Baseline commit (40 characters)'), { exact: true }).fill('a'.repeat(40));
    await dialog.getByLabel(await t('Test image reference'), { exact: true }).fill('company/tests:v1');
    await dialog.getByRole('button', { name: await t('Next'), exact: true }).click();
    await dialog.getByLabel(await t('Task prompt · agent-visible'), { exact: true }).fill('Implement the required behavior');
    await dialog.getByRole('combobox', { name: await t('Agent launch mode'), exact: true }).selectOption('command');
    await dialog.getByLabel(await t('Custom Agent image'), { exact: true }).fill('company/agent:v2');
    await dialog.getByRole('textbox', { name: await t('Agent startup command'), exact: true }).fill('my-agent < "$CTXBENCH_PROMPT_FILE"');
    await dialog.getByRole('combobox', { name: await t('Test command template'), exact: true }).selectOption('maven');
    const folder = resolve('artifacts/image-workshop-ui'); await mkdir(folder, { recursive: true });
    await page.screenshot({ path: resolve(folder, `custom-agent-${locale}.png`) });
    await dialog.getByRole('button', { name: await t('Next'), exact: true }).click();
    await dialog.getByRole('button', { name: await t('Save evaluation case'), exact: true }).click();
    await page.waitForFunction(() => !!window.savedCase);
    const saved = await page.evaluate(() => window.savedCase.row);
    assert.deepEqual(saved.agent, { image: 'company/agent:v2', command: ['/bin/sh', '-eu', '-c', 'my-agent < "$CTXBENCH_PROMPT_FILE"'] });
    assert.equal(saved.test.command.at(-1), 'mvn -B test');
    await page.getByRole('button', { name: 'Open experiment fixture', exact: true }).click();
    await dialog.getByLabel(await t('Experiment name'), { exact: true }).fill('Unknown tokens are not a grading error');
    await dialog.getByRole('combobox', { name: await t('Context comparison'), exact: true }).selectOption('developer-historical');
    await dialog.getByRole('button', { name: await t('Continue to execution'), exact: true }).click();
    const solver = dialog.getByRole('group', { name: await t('solver'), exact: true });
    await solver.getByLabel(await t('Provider'), { exact: true }).fill('company');
    await solver.getByLabel(await t('Model'), { exact: true }).fill('company-agent-model');
    await dialog.getByRole('combobox', { name: await t('Shared token budget'), exact: true }).selectOption('exhausted');
    assert.equal(await solver.getByLabel(await t('Model'), { exact: true }).inputValue(), 'company-agent-model');
    await dialog.getByRole('button', { name: await t('Continue to review'), exact: true }).click();
    await dialog.getByRole('button', { name: await t('Create & prepare'), exact: true }).click();
    await page.waitForFunction(() => !!window.experiment);
    const experiment = await page.evaluate(() => window.experiment);
    assert.equal(experiment.budgetId, 'exhausted'); assert.equal(experiment.model.model, 'company-agent-model');
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ locale, pullFailureAndRetry: true, recipePreviewBuild: true, independentAgentCommandSaved: true, unknownUsageDoesNotBlockExperiment: true }));
    await page.close();
  }
} finally { await browser.close(); await server.close(); }
