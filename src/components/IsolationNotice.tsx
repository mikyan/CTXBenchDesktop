import { useI18n } from '../i18n';
import type { DesktopConnection } from '../lib/desktop';

export function IsolationNotice({ connection }: { connection?: DesktopConnection }) {
  const { t } = useI18n();
  if (!connection?.isolated) return null;
  return <div className="connection-banner isolation-notice" role={connection.error ? 'alert' : 'status'}>
    <strong>{t('Isolated acceptance instance — not your production workspace')}</strong>
    {connection.baseUrl && <code>{connection.baseUrl}</code>}
    <span>{t('Production service controls and application image installation are disabled. Custom image adaptation, cases, experiments and image export remain available.')}</span>
    {connection.error && <span>{t(connection.error)}</span>}
  </div>;
}
