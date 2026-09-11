import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { translate } from '../i18n';
import { I18nContext } from '../i18n.context';
import { ImageRecipeGuide } from '../components/ImageRecipeGuide';
import { RemoteImagePull } from '../components/RemoteImagePull';
import { CustomAgentFields } from '../components/CustomAgentFields';
import { guidedDockerfile } from './image-recipes';
import { LocalImageSelect, localImageChoices } from '../components/LocalImageSelect';
import { BuildFilePicker } from '../components/BuildFilePicker';
import { datasetRows, draftFromManifest, draftIssues } from './dataset-authoring';

describe('image workshop and command Agents', () => {
  it('repairs default HOME after root installation and probes it as the runtime UID', () => {
    const commands = 'mkdir -p /home/ctxbench/.local/share/fixture/log';
    const recipe = guidedDockerfile(commands, 'HOME=/home/ctxbench', []);
    const guard = 'test ! -L /home && test ! -L /home/ctxbench';
    expect(recipe.split('\n')[1]).toContain(guard);
    expect(recipe.indexOf(guard)).toBeLessThan(recipe.indexOf('chown'));
    expect(recipe.lastIndexOf('chown -R -h 10001:10001 /home/ctxbench')).toBeGreaterThan(recipe.indexOf(commands));
    expect(recipe).toContain('USER 10001:10001\nRUN test -w /home/ctxbench && test -x /home/ctxbench\nUSER root');
    expect(guidedDockerfile('', 'HOME=/operator/custom-home', [])).not.toContain('chown -R -h 10001:10001 /operator');
    expect(guidedDockerfile('', 'HOME=/home/ctxbench', [])).toContain('chown -R -h');
  });
  it.each(['en', 'zh-CN'] as const)('shows authoritative loaded file status instead of an empty native chooser in %s', (locale) => {
    const value = { locale, setLocale() {}, t: (key: string, values?: Record<string, string | number>) => translate(locale, key, values) };
    for (const count of [0, 1, 2]) {
      const html = renderToStaticMarkup(<I18nContext.Provider value={value}><BuildFilePicker label="Non-secret configuration files" count={count} onSelect={() => {}} /></I18nContext.Provider>);
      expect(html).toMatch(/<input[^>]+type="file"[^>]+hidden=""/);
      expect(html).toContain(translate(locale, count ? 'Replace loaded files' : 'Choose build files'));
      expect(html).toContain(translate(locale, count ? '{count} files loaded. Choosing again replaces this list; cancelling keeps it.' : 'No build files loaded. Adding configuration files is optional.', { count }));
    }
  });
  it('lists only installed image choices without inventing bundled availability or overwriting a manual choice', () => {
    expect(localImageChoices(['team/z:v1', '<none>:<none>', 'team/a:v1', 'team/z:v1', ''])).toEqual(['team/a:v1', 'team/z:v1']);
  });
  it.each(['en', 'zh-CN'] as const)('shows discovery and manual fallback in the first recipe step in %s', (locale) => {
    const value = { locale, setLocale() {}, t: (key: string, values?: Record<string, string | number>) => translate(locale, key, values) };
    const html = renderToStaticMarkup(<I18nContext.Provider value={value}><ImageRecipeGuide distribution="Ubuntu" onApply={() => {}} /><LocalImageSelect distribution="" value="manual/base:v1" onChange={() => {}} /></I18nContext.Provider>);
    expect(html).toContain(translate(locale, 'Choose an installed base image'));
    expect(html).toContain(translate(locale, 'Local base image'));
    expect(html).toContain(translate(locale, 'Refresh local images'));
    expect(html).toContain('Node.js/npm');
    expect(html).toContain(translate(locale, 'Select an installed WSL distribution first.'));
  });
  it('preserves multiline commands literally in JSON RUN, copying files before setup', () => {
    const command = 'echo "one"\necho "$HOME"';
    const recipe = guidedDockerfile(command, 'LANG=C.UTF-8', [{ path: 'settings.json', base64: 'e30=' }]);
    const run = recipe.split('\n').find((line) => line.startsWith('RUN ['))!;
    expect(JSON.parse(run.slice(4))).toEqual(['/bin/sh', '-eu', '-c', command]);
    expect(recipe.indexOf('COPY')).toBeLessThan(recipe.indexOf('RUN ['));
    expect(recipe).not.toContain('FROM ');
  });
  it('rejects credential defaults, duplicate settings and path escapes', () => {
    for (const defaults of ['API_KEY=not-for-images', 'X=1\nX=2', 'no equals']) expect(() => guidedDockerfile('', defaults, [])).toThrow();
    expect(() => guidedDockerfile('', '', [{ path: '../secret', base64: '' }])).toThrow();
  });
  it('round trips Agent command separately from grading and does not invent it for legacy cases', () => {
    const row = { id: 'one', repository: 'https://git.example/repo', baseCommit: 'a'.repeat(40), image: 'tests:v1', prompt: 'Fix', test: { command: ['mvn', 'test'] } };
    const custom = { ...row, agent: { image: 'agent:v1', command: ['agent', '--stdin'] } };
    const draft = draftFromManifest('Case', [custom]);
    expect(draftIssues(draft)).toEqual([]);
    expect(datasetRows(draft)).toEqual([custom]);
    expect(datasetRows(draftFromManifest('Legacy', [row]))[0]).not.toHaveProperty('agent');
  });
  it.each(['en', 'zh-CN'] as const)('renders the distinct guided entries in %s', (locale) => {
    const html = renderToStaticMarkup(<I18nContext.Provider value={{ locale, setLocale: () => {}, t: (key, values) => translate(locale, key, values) }}><ImageRecipeGuide onApply={() => {}} /><RemoteImagePull /><CustomAgentFields value={{ image: 'agent:v1', command: 'agent', commandMode: 'shell' }} onChange={() => {}} /></I18nContext.Provider>);
    expect(html).toContain('CTXBENCH_PROMPT_FILE');
    expect(html).toContain(locale === 'en' ? 'Pull an existing image' : '拉取现成镜像');
    expect(html).toContain(locale === 'en' ? 'Build your image step by step' : '一步步制作自己的镜像');
    expect(html).toContain(translate(locale, 'Already installed the tools? Choose that local image as the base and leave dependency commands empty. The guide still prepares the default HOME for UID 10001; no reinstall is needed. Build a new tag, then select it in your case for future experiments.'));
  });
});
