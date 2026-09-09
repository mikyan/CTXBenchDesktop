import { useEffect, useState } from 'react';
import { useI18n } from '../i18n';
import { workerRequest } from '../lib/desktop';

interface Selection { taskId: string; connectionName: string; repository: string; provider: string; credentialConfigured: boolean }
export function CISelectionNotice({ dataset, selected }: { dataset: string; selected: string[] }) {
  const { t } = useI18n(); const [rows, setRows] = useState<Selection[]>([]);
  useEffect(() => { let active = true; setRows([]); if (dataset) void workerRequest<Selection[]>(`/ci/selection/${dataset}`).then((value) => { if (active) setRows(value); }).catch(() => { /* Old workers still validate definitions server-side. */ }); return () => { active = false; }; }, [dataset]);
  const ci = rows.filter((row) => selected.includes(row.taskId));
  if (!ci.length) return null;
  return <div className="wizard-notice"><strong>{t('Selected cases use remote CI grading')}</strong><p>{t('These cases upload candidate code and trigger external workflows during grading. Each arm and repeat uses a separate evaluation branch. Pausing local work does not pause the remote platform.')}</p>
    <ul>{ci.map((row) => <li key={row.taskId}>{row.taskId} · {row.connectionName} · {row.repository} · {t(row.credentialConfigured ? 'Configured' : 'Platform token missing')}</li>)}</ul>
    <p>{t('For CI cases, the local project image supplies Agent tools; the remote workflow supplies the final build and test environment. Configure the token in the case editor before starting.')}</p>
  </div>;
}
