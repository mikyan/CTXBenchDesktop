import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { I18nContext } from '../i18n.context';
import { translate } from '../i18n';
import { ciChinese } from '../i18n.ci';
import { datasetRows, draftFromManifest, draftIssues, newDatasetDraft } from './dataset-authoring';
import { defaultCITest, CIGradingFields } from '../components/CIGradingFields';
import { CIGradingResult } from '../components/CIGradingResult';
import { DatasetSelfTest } from '../components/DatasetSelfTest';
import type { BenchmarkRun } from '../domain/types';

function draft() {
  const value = newDatasetDraft(); value.name = 'CI case';
  Object.assign(value.defaults, { repository: 'https://github.com/team/backend.git', baseCommit: 'a'.repeat(40), image: 'company/java:17' });
  Object.assign(value.tasks[0], { prompt: 'Fix API behavior.', ci: { ...defaultCITest(), connectionId: 'b'.repeat(64), requiredJobs: [' build ', 'test', ''], allowRemoteExecution: true } });
  return value;
}
function render(children: React.ReactNode, locale: 'en' | 'zh-CN' = 'zh-CN') {
  return renderToStaticMarkup(<I18nContext.Provider value={{ locale, setLocale: () => {}, t: (key, args) => translate(locale, key, args) }}>{children}</I18nContext.Provider>);
}
describe('pluggable CI grading', () => {
  it('exports CI instead of an invented local command and round-trips editable settings', () => {
    const value = draft(); expect(draftIssues(value)).toEqual([]);
    const rows = datasetRows(value);
    expect(rows[0].test.command).toBeUndefined(); expect(rows[0].test.ci?.requiredJobs).toEqual(['build', 'test']);
    expect(datasetRows(draftFromManifest(value.name, rows))).toEqual(rows);
    expect(rows[0].prompt).toBe('Fix API behavior.');
  });
  it('requires explicit upload consent and never silently discards hidden or reference patches', () => {
    const value = draft(); value.tasks[0].ci!.allowRemoteExecution = false;
    expect(() => datasetRows(value)).toThrow();
    value.tasks[0].ci!.allowRemoteExecution = true; value.tasks[0].goldPatch = 'PRIVATE_FIX';
    expect(() => datasetRows(value)).toThrow();
  });
  it('renders both platform choices, clear scope and no local self-test for remote cases', () => {
    for (const locale of ['en', 'zh-CN'] as const) {
      const html = render(<CIGradingFields value={draft().tasks[0].ci!} onChange={() => {}} />, locale);
      expect(html).toContain('GitHub Actions / Enterprise'); expect(html).toContain(translate(locale, 'Company HTTP CI gateway'));
      expect(html).toContain('workflow_dispatch');
      const selfTest = render(<DatasetSelfTest payload={JSON.stringify({ rows: datasetRows(draft()) })} />, locale);
      expect(selfTest).not.toContain('<button'); expect(selfTest).toContain(translate(locale, 'CI: the local self-test never uploads code. Run CI cases through an explicitly configured experiment.'));
    }
  });
  it('does not substitute job count for unknown test counts and displays reported counts', () => {
    const run = { grade: { gradingMode: 'ci', ci: { status: 'completed', remoteId: 1 }, requiredJobs: [{ name: 'test', conclusion: 'success' }] } } as BenchmarkRun;
    expect(render(<CIGradingResult run={run} />)).toContain('未提供单测数量');
    run.grade = { ...(run.grade as object), testCounts: { total: 5, passed: 4, failures: 1, errors: 0, skipped: 0 } };
    expect(render(<CIGradingResult run={run} />)).toContain('测试总数');
    expect(render(<CIGradingResult run={run} />)).not.toContain('未提供单测数量');
  });
  it('translates every CI label', () => {
    for (const [key, value] of Object.entries(ciChinese)) expect(translate('zh-CN', key)).toBe(value);
  });
});
