import { useState } from 'react';
import type { DatasetRecord } from '../domain/types';
import { useI18n } from '../i18n';
import { benchmarkLabel } from '../lib/benchmark-labels';

export function LibrarySourcePicker({ value, onChange, sources, onReload }: {
  value: string; onChange: (value: string) => void; sources: DatasetRecord[]; onReload?: () => void;
}) {
  const { t } = useI18n();
  const [query, setQuery] = useState('');
  const visible = sources.filter((item) => item.id === value || item.name.toLowerCase().includes(query.toLowerCase()));
  return <fieldset className="library-source"><legend>{t('Select a case or dataset')}</legend>
    <label>{t('Search cases or datasets')}<input value={query} onChange={(e) => setQuery(e.target.value)} /></label>
    <label>{t('Evaluation source')}<select value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">{t('Choose an existing case or dataset')}</option>
      <optgroup label={t('Evaluation cases')}>{visible.filter((item) => item.id.startsWith('case-')).map((item) => <option key={item.id} value={item.id}>{item.name} · {benchmarkLabel(item.benchmark, t)}</option>)}</optgroup>
      <optgroup label={t('Datasets')}>{visible.filter((item) => !item.id.startsWith('case-')).map((item) => <option key={item.id} value={item.id}>{item.name} · {item.count} {t('Tasks')}</option>)}</optgroup>
    </select></label>
    {onReload && <button type="button" className="text-button" onClick={onReload}>{t('Reload current selection')}</button>}
    <p>{t('A single case can run without a dataset. Starting creates an immutable snapshot; later edits do not change queued or historical runs.')}</p>
  </fieldset>;
}
