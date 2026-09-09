import { useState } from 'react';
import { useI18n } from '../i18n';
import { workerRequest } from '../lib/desktop';
import type { LibraryInventory, LibrarySet } from '../lib/case-library';
import { libraryError } from '../lib/case-library';
import { benchmarkLabel } from '../lib/benchmark-labels';
import { Modal, FormError } from './Dialogs';

export function SetEditor({ collection, library, onClose, onSaved }: {
  collection?: LibrarySet; library: LibraryInventory; onClose: () => void; onSaved: () => void;
}) {
  const { t } = useI18n();
  const [name, setName] = useState(collection?.name ?? '');
  const [ids, setIds] = useState(collection?.caseIds ?? []);
  const [query, setQuery] = useState('');
  const [error, setError] = useState(''); const [busy, setBusy] = useState(false);
  const selected = ids.map((id) => library.cases.find((item) => item.id === id)).filter((item) => !!item);
  const protocol = selected[0]?.benchmark;
  const visible = library.cases.filter((item) => `${item.name} ${item.taskId} ${item.repository}`.toLowerCase().includes(query.toLowerCase()));
  const save = async () => {
    setBusy(true); setError('');
    try { await workerRequest(collection ? `/library/sets/${collection.id}` : '/library/sets', collection ? 'PUT' : 'POST', {
      name, caseIds: ids, ...(collection ? { expectedRevision: collection.revision } : {}),
    }); onSaved(); onClose(); } catch (cause) { setError(libraryError(cause)); } finally { setBusy(false); }
  };
  const dirty = name !== (collection?.name ?? '') || JSON.stringify(ids) !== JSON.stringify(collection?.caseIds ?? []);
  return <Modal title={t(collection ? 'Edit dataset composition' : 'Compose dataset')} busy={busy} warnOnClose dirty={dirty} onClose={onClose}>
    <p>{t('A dataset references existing cases; it does not copy them. Editing a shared case updates future runs of every referencing dataset. Historical snapshots stay unchanged.')}</p>
    <fieldset disabled={busy}>
      <label>{t('Dataset name')}<input autoFocus value={name} onChange={(e) => setName(e.target.value)} /></label>
      {collection && <p>{t('Editing revision {revision}', { revision: collection.revision })}</p>}
      <label>{t('Search evaluation cases')}<input value={query} onChange={(e) => setQuery(e.target.value)} /></label>
      <p>{t('Combine cases using the same grading protocol. SWE-bench, CTXBench and custom tests use different graders.')}</p>
      <div className="task-picker">{visible.map((item) => <label className="check-line" key={item.id}>
        <input type="checkbox" checked={ids.includes(item.id)} disabled={Boolean(protocol && protocol !== item.benchmark)} onChange={(e) => setIds(e.target.checked ? [...ids, item.id] : ids.filter((id) => id !== item.id))} />
        <span>{item.name}<small>{item.taskId} · {benchmarkLabel(item.benchmark, t)} · v{item.revision}</small></span>
      </label>)}</div>
      {!library.cases.length && <p>{t('Create a case or import standard cases first, then compose a dataset here.')}</p>}
      <h3>{t('Selected cases ({count})', { count: ids.length })}</h3>
      <p>{t('Selections remain selected when you search. Removing a case here does not delete it from the case library.')}</p>
      <ol className="selected-cases">{selected.map((item) => <li key={item.id}><span>{item.name} · v{item.revision}</span><button type="button" className="text-button" onClick={() => setIds(ids.filter((id) => id !== item.id))}>{t('Remove from dataset')}</button></li>)}</ol>
    </fieldset>
    {error && <FormError>{t(error)}</FormError>}
    <button className="button primary" disabled={busy || !name.trim() || !ids.length} onClick={() => void save()}>{t(collection ? 'Save dataset changes' : 'Create dataset')}</button>
  </Modal>;
}
