import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { translate } from '../i18n';
import { I18nContext } from '../i18n.context';
import { ImageRecipeGuide } from '../components/ImageRecipeGuide';
import { RemoteImagePull } from '../components/RemoteImagePull';
import { CustomAgentFields } from '../components/CustomAgentFields';
import { guidedDockerfile } from './image-recipes';
import { datasetRows, draftFromManifest, draftIssues } from './dataset-authoring';

describe('image workshop and command Agents', () => {
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
  });
});
