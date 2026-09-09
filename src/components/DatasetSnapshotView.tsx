import { useEffect, useState } from 'react';
import { useI18n } from '../i18n';
import type { DatasetSnapshot } from '../lib/case-library';
import type { TaskSummary } from '../domain/types';
import { saveText, workerRequest } from '../lib/desktop';
import { Modal, FormError } from './Dialogs';

export function DatasetSnapshotBadge({ snapshot }: { snapshot?: DatasetSnapshot }) {
  const { t } = useI18n(); const [open, setOpen] = useState(false);
  if (!snapshot?.id) return null;
  return <><button className="text-button" onClick={() => setOpen(true)}>{t('View run snapshot')} · {snapshot.name} v{snapshot.sourceRevision}</button>{open && <DatasetSnapshotView id={snapshot.id} onClose={() => setOpen(false)} />}</>;
}
export function DatasetSnapshotView({ id, onClose }: { id: string; onClose: () => void }) {
  const { t } = useI18n();
  const [record, setRecord] = useState<DatasetSnapshot & { tasks: TaskSummary[] }>(); const [error, setError] = useState('');
  useEffect(() => { let alive = true; void workerRequest<NonNullable<typeof record>>(`/library/snapshots/${id}`).then((value) => { if (alive) setRecord(value); }).catch((cause) => { if (alive) setError(String(cause)); }); return () => { alive = false; }; }, [id]);
  return <Modal title={t('Immutable run snapshot')} onClose={onClose}>
    <p>{t('This is the definition captured before execution, not the latest editable case. Hidden tests and reference fixes remain on the evaluator side.')}</p>
    {error && <FormError>{t(error)}</FormError>}
    {record ? <><h3>{record.name}</h3><p>{record.createdAt}</p><code>{record.id}</code>
      {record.tasks.map((task) => <details key={task.id}><summary>{task.id} · v{record.members.find((item) => item.taskId === task.id)?.revision}</summary><p>{task.repository}</p><code>{task.baseCommit}</code><p className="task-prompt">{task.prompt}</p></details>)}
      <details><summary>{t('Frozen metadata and hashes')}</summary><pre>{JSON.stringify(record, null, 2)}</pre></details>
      <button className="button secondary" onClick={() => void saveText(`${id}.json`, JSON.stringify(record, null, 2)).catch((cause) => setError(String(cause)))}>{t('Export snapshot metadata')}</button>
    </> : <p role="status">{t('Loading…')}</p>}
  </Modal>;
}
