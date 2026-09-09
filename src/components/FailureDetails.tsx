import { useI18n } from '../i18n';

import type { FailureDiagnostic } from '../domain/types';
export type { FailureDiagnostic } from '../domain/types';

export function FailureDetails({ diagnostic, message, onLogs }: { diagnostic?: FailureDiagnostic; message?: string; onLogs?: () => void }) {
  const { t } = useI18n();
  if (!diagnostic && !message) return null;
  return <section className="failure-details" aria-label={t('Failure details')}>
    {diagnostic && <><strong>{t('Failed step')}: {t(diagnostic.stage)}</strong>
      <p>{t(diagnostic.agentStarted ? 'An Agent container has started; check execution records for model usage.' : 'No Agent container start was recorded for this attempt.')}</p></>}
    <pre>{diagnostic?.summary || message}</pre>
    {diagnostic?.hint && <p>{t(diagnostic.hint)}</p>}
    {onLogs && <button type="button" className="button secondary" onClick={onLogs}>{t('View complete execution log')}</button>}
  </section>;
}
