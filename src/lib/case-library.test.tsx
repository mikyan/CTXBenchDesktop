import { createElement, type ReactNode } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { I18nContext } from '../i18n.context';
import { translate } from '../i18n';
import { caseLibraryChinese } from '../i18n.case-library';
import { libraryError, librarySources, selectionCases, type LibraryInventory } from './case-library';
import { CaseEditor } from '../components/CaseEditor';
import { SetEditor } from '../components/SetEditor';
import { LibrarySourcePicker } from '../components/LibrarySourcePicker';
import { DatasetSnapshotBadge } from '../components/DatasetSnapshotView';
import { Sidebar } from '../components/Sidebar';

const noop = () => {};
function render(element: ReactNode, locale: 'en' | 'zh-CN' = 'en') {
  return renderToStaticMarkup(createElement(I18nContext.Provider, { value: { locale, setLocale: noop, t: (key, values) => translate(locale, key, values) } }, element));
}
const sample = { id: 'case-one', name: 'Service regression', taskId: 'task-1', benchmark: 'custom' as const,
  revision: 2, repository: 'https://git.example/team/service.git', baseCommit: 'a'.repeat(40), prompt: 'Repair behavior',
  image: 'company/test:v1', createdAt: '2026-09-08', updatedAt: '2026-09-08', modified: false };
const inventory: LibraryInventory = { version: 1, cases: [sample, { ...sample, id: 'case-two', taskId: 'task-2' }, { ...sample, id: 'case-official', benchmark: 'swebench' }],
  sets: [{ id: 'set-one', name: 'Service suite', benchmark: 'custom', revision: 3, caseIds: ['case-two', 'case-one'], count: 2, createdAt: '2026-09-08', updatedAt: '2026-09-08' }] };

describe('editable case library', () => {
  it('keeps all Chinese labels active', () => {
    for (const [key, value] of Object.entries(caseLibraryChinese)) expect(translate('zh-CN', key), key).toBe(value);
  });
  it('gives cases their own navigation entry', () => {
    const html = render(<Sidebar page="cases" onNavigate={noop} />, 'zh-CN');
    expect(html).toContain('评测用例'); expect(html).toContain('评测集');
    expect(html.match(/aria-current="page"/g)).toHaveLength(1);
  });
  it('creates a case independently without an embedded dataset wizard', () => {
    const html = render(<CaseEditor onClose={noop} onSaved={noop} />, 'zh-CN');
    expect(html).toContain('创建评测用例'); expect(html).toContain('仓库与环境');
    expect(html).toContain('任务与测试'); expect(html).not.toContain('评测集名称');
    expect(html).not.toContain('共享默认值');
  });
  it('composes references and disables incompatible grading protocols', () => {
    const html = render(<SetEditor collection={inventory.sets[0]} library={inventory} onClose={noop} onSaved={noop} />);
    expect(html).toContain('references existing cases');
    expect(html).toContain('Removing a case here does not delete it');
    expect(html).toContain('type="checkbox" disabled=""');
    expect(html).toContain('Selected cases (2)');
    expect(html).not.toContain('Task prompt · agent-visible');
  });
  it('preserves composition ordering and reads latest member revision', () => {
    expect(selectionCases(inventory, inventory.sets[0]).map((item) => item.id)).toEqual(['case-two', 'case-one']);
    expect(librarySources(inventory).map((item) => item.id)).toEqual(['set-one', 'case-one', 'case-two', 'case-official']);
    expect(librarySources(inventory)[1].count).toBe(1);
  });
  it('allows direct case selection and explains run snapshotting', () => {
    const html = render(<LibrarySourcePicker value="case-one" onChange={noop} sources={librarySources(inventory)} onReload={noop} />);
    expect(html).toContain('<optgroup label="Evaluation cases">');
    expect(html).toContain('value="case-one" selected=""');
    expect(html).toContain('Starting creates an immutable snapshot');
    expect(html).toContain('Reload current selection');
  });
  it('does not fabricate a snapshot for historical plans', () => {
    expect(render(<DatasetSnapshotBadge />)).toBe('');
  });
  it('provides upgrade guidance without masking revision conflicts', () => {
    expect(libraryError(new Error('Not Found'))).toContain('matching desktop and evaluation service images');
    expect(libraryError(new Error('The selected cases or dataset changed.'))).toBe('The selected cases or dataset changed.');
  });
});
