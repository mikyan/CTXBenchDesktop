import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import type { ReactNode } from 'react';
import type { KnowledgeArtifact, TaskSummary } from '../domain/types';
import { I18nContext } from '../i18n.context';
import { translate, type Locale } from '../i18n';
import { experimentGuidanceChinese } from '../i18n.experiment-guidance';
import { FrozenPackagePicker, matchingPackages } from '../components/FrozenPackagePicker';
import { AgentImageReview } from '../components/AgentImageReview';

const task = { id: 'fixture-task', repository: 'https://git.example/repo', baseCommit: 'a'.repeat(40) } as TaskSummary;
const artifact = { id: 'matching', repository: task.repository, commit: task.baseCommit, status: 'ready', source: 'manual', files: 1 } as KnowledgeArtifact;
const noop = () => {};
const render = (node: ReactNode, locale: Locale) => renderToStaticMarkup(<I18nContext.Provider value={{ locale, setLocale: noop, t: (key, values) => translate(locale, key, values) }}>{node}</I18nContext.Provider>);

describe('experiment preparation guidance', () => {
  it('keeps every added Chinese translation active', () => {
    for (const [key, value] of Object.entries(experimentGuidanceChinese)) expect(translate('zh-CN', key)).toBe(value);
  });
  it('does not relax repository or immutable commit matching', () => {
    expect(matchingPackages(task, [artifact, { ...artifact, id: 'other-repo', repository: task.repository + '.git' }, { ...artifact, id: 'other-sha', commit: 'b'.repeat(40) }])).toEqual([artifact]);
  });
  it.each(['en', 'zh-CN'] as const)('distinguishes genuinely empty/mismatched/unready packages in %s', locale => {
    const sets = [
      { items: [], key: 'No knowledge packages have been imported or generated yet.' },
      { items: [{ ...artifact, commit: 'b'.repeat(40) }], key: 'No package matches this repository and baseline commit.' },
      { items: [{ ...artifact, status: 'generating' as const }, { ...artifact, id: 'invalid', status: 'invalid' as const }], key: 'Matching packages are still generating or invalid. Wait for generation to finish, or import a ready package.' },
    ];
    for (const { items, key } of sets) {
      const html = render(<FrozenPackagePicker tasks={[task]} artifacts={items} values={{}} onChange={noop} onImport={noop} />, locale);
      expect(html).toContain(translate(locale, key)); expect(html).toContain(task.baseCommit);
      expect(html).toContain(translate(locale, 'Import a matching package'));
      expect(html).not.toContain('<option value="matching"');
    }
  });
  it.each(['en', 'zh-CN'] as const)('never reports a loading/error state as absence in %s', locale => {
    for (const state of [{ loading: true }, { failed: true }]) {
      const html = render(<FrozenPackagePicker tasks={[task]} artifacts={[]} values={{}} onChange={noop} onImport={noop} onRefresh={noop} {...state} />, locale);
      expect(html).not.toContain(translate(locale, 'No knowledge packages have been imported or generated yet.'));
      expect(html).toContain(translate(locale, 'loading' in state ? 'Loading knowledge packages…' : 'Could not refresh knowledge packages. The list may be out of date; retry before selecting a package.'));
      expect(html).toMatch(/<select[^>]*disabled=""/);
    }
  });
  it.each(['en', 'zh-CN'] as const)('explains custom and composed/default images separately in %s', locale => {
    const tasks = [{ ...task, customAgentImage: 'team/opencode:v1' }, { ...task, id: 'default-task' }];
    const html = render(<AgentImageReview tasks={tasks} image="team/pi:v1" projectEnvironment generatesContext />, locale);
    expect(html).toContain('team/opencode:v1'); expect(html).toContain('team/pi:v1');
    for (const key of ['Case override — uses the custom command and image.', 'Experiment base — combined with the project environment during preparation.', 'Knowledge builder base image']) expect(html).toContain(translate(locale, key));
    const customOnly = render(<AgentImageReview tasks={[tasks[0]]} image="team/pi:v1" projectEnvironment generatesContext={false} />, locale);
    expect(customOnly).not.toContain('team/pi:v1');
    expect(customOnly).not.toContain(translate(locale, 'Knowledge builder base image'));
    const unchanged = render(<AgentImageReview tasks={[tasks[1]]} image="team/pi:v1" projectEnvironment={false} generatesContext={false} />, locale);
    expect(unchanged).toContain(translate(locale, 'Experiment default — used without project dependency composition.'));
  });
});
