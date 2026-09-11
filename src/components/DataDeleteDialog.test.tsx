import { describe, expect, it } from 'vitest';
import { createElement, type ReactElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { DataDeleteDialog, deletionError } from './DataDeleteDialog';
import { translate } from '../i18n';
import { deletionsChinese } from '../i18n.deletions';
import { ConfirmDialog } from './Dialogs';
import { I18nContext } from '../i18n.context';

const render = (element: ReactElement) => renderToStaticMarkup(createElement(I18nContext.Provider, { value: { locale: 'en', setLocale() {}, t: (key, values) => translate('en', key, values) } }, element));

describe('data deletion safeguards', () => {
  it('cannot confirm before the service provides the current impact', () => {
    const markup = render(createElement(DataDeleteDialog, { target: { kind: 'case', id: 'fixture' }, onClose() {}, onDeleted() {} }));
    expect(markup).toContain('role="alertdialog"');
    expect(markup).toContain('Checking deletion impact');
    expect(markup).toContain('disabled=""');
    expect(markup).toContain('Frozen snapshots');
  });
  it('disables both actions while confirming and focuses the safe action first', () => {
    const markup = render(createElement(ConfirmDialog, { title: 'Delete?', description: 'Impact', confirmLabel: 'Confirm', cancelLabel: 'Keep', busy: true, onCancel() {}, onConfirm() {} }));
    expect(markup.match(/disabled=""/g)).toHaveLength(2);
    expect(markup).toContain('autofocus=""');
    expect(markup).toContain('role="status"');
  });
  it('gives actionable instructions for an old service or a missing record', () => {
    expect(deletionError(Error('Not Found'))).toContain('matching desktop and evaluation service images');
    expect(deletionError('Record not found: case-old')).toContain('Close this dialog and refresh');
    expect(deletionError(Error('Network failed'))).toBe('Network failed');
  });
  it.each(Object.keys(deletionsChinese))('translates deletion copy: %s', (key) => {
    expect(translate('zh-CN', key)).toBe(deletionsChinese[key]);
    expect(translate('en', key)).toBe(key);
  });
});
