import { useEffect, useState } from 'react';
import { useI18n } from '../i18n';
import { workerRequest } from '../lib/desktop';
import { ConfirmDialog, FormError } from './Dialogs';

export type DeletionTarget = { kind: 'case' | 'set' | 'experiment' | 'result'; id: string };
export interface DeletionPlan extends DeletionTarget {
  name: string; token: string; runCount: number; caseCount?: number;
  pairId?: string; taskId?: string; repeat?: number; arms?: string[]; blockers: string[];
  affectedSets: { id: string; name: string; revision: number; remainingCount: number }[];
}
const titles = { case: 'Delete evaluation case?', set: 'Delete dataset?', experiment: 'Delete experiment and all results?', result: 'Delete this complete comparison group?' };

export function deletionError(cause: unknown): string {
  const message = String(cause).replace(/^Error: /, '');
  if (/(?:^|Error: )Not Found$/i.test(message)) return 'Deletion requires matching desktop and evaluation service images. Update the application images and restart the service safely; existing data is preserved.';
  if (message.startsWith('Record not found:')) return 'This record no longer exists. Close this dialog and refresh the list.';
  return message;
}

export function DataDeleteDialog({ target, onClose, onDeleted }: { target: DeletionTarget; onClose: () => void; onDeleted: () => void }) {
  const { t } = useI18n();
  const [plan, setPlan] = useState<DeletionPlan>();
  const [loading, setLoading] = useState(true); const [busy, setBusy] = useState(false);
  const [error, setError] = useState(''); const [revision, reload] = useState(0);
  useEffect(() => {
    let alive = true;
    setLoading(true); setPlan(undefined); setError('');
    void workerRequest<DeletionPlan>('/data-deletions/preview', 'POST', { kind: target.kind, id: target.id })
      .then((value) => { if (alive) setPlan(value); })
      .catch((cause) => { if (alive) setError(deletionError(cause)); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [target.kind, target.id, revision]);
  const remove = async () => {
    if (!plan || busy || loading || plan.blockers.length) return;
    setBusy(true); setError('');
    try {
      await workerRequest('/data-deletions', 'POST', { kind: plan.kind, id: plan.id, token: plan.token });
      onDeleted(); onClose();
    } catch (cause) {
      setError(deletionError(cause)); setPlan(undefined);
    } finally { setBusy(false); }
  };
  return <ConfirmDialog title={t(titles[target.kind])} description={t('Deletion cannot be undone here. Review the exact impact before confirming.')} busy={busy}
    confirmLabel={t('Confirm deletion')} cancelLabel={t('Keep data')} disabled={busy || loading || !plan || !!plan.blockers.length}
    onCancel={onClose} onConfirm={() => void remove()}>
    {loading && <p role="status">{t('Checking deletion impact…')}</p>}
    {plan && <div className="deletion-impact">
      <strong>{plan.name}</strong>
      {plan.kind === 'case' && <><p>{t('This case definition will be deleted and removed from {count} datasets.', { count: plan.affectedSets.length })}</p>
        {!!plan.affectedSets.length && <ul>{plan.affectedSets.map((item) => <li key={item.id}>{item.name} · {t('{count} cases remaining', { count: item.remainingCount })}{!item.remainingCount && ` · ${t('Empty dataset: add cases before running again')}`}</li>)}</ul>}</>}
      {plan.kind === 'set' && <p>{t('Only this dataset composition will be deleted. Its {count} independent cases are kept.', { count: plan.caseCount ?? 0 })}</p>}
      {plan.kind === 'experiment' && <p>{t('The experiment and all {count} result records will be deleted and excluded from statistics and exports.', { count: plan.runCount })}</p>}
      {plan.kind === 'result' && <><p>{plan.taskId} · {t('Repeat')} {plan.repeat}</p><p>{t('All {count} arms of this case and repeat will be deleted together, including the no-context baseline. Other comparison groups are kept.', { count: plan.runCount })}</p><code>{plan.pairId}</code></>}
      {!!plan.blockers.length && <div role="alert" className="form-error">{plan.blockers.map((item) => <p key={item}>{t(item)}</p>)}</div>}
    </div>}
    <p>{t('Frozen snapshots, knowledge packages, token accounting, Docker images, repository caches, evidence files and saved logs are kept. This does not stop remote CI workflows or free their storage.')}</p>
    {error && <FormError>{t(error)}</FormError>}
    {error && <p>{t('If the connection was interrupted, refresh the list to check whether deletion already completed before trying again.')}</p>}
    <button type="button" className="button secondary" disabled={busy || loading} onClick={() => reload((value) => value + 1)}>{t('Reload deletion preview')}</button>
  </ConfirmDialog>;
}
