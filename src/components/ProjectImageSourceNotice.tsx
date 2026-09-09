import { useEffect, useState } from 'react';
import { useI18n } from '../i18n';
import { workerRequest } from '../lib/desktop';

/** Read-only reminder; the execution service captures the authoritative copy. */
export function ProjectImageSourceNotice({ dataset, profileId }: { dataset: string; profileId: string }) {
  const { t } = useI18n();
  const [rows, setRows] = useState<{ source: string; target: string }[]>([]);
  useEffect(() => { let active = true; setRows([]);
    if (dataset) void workerRequest<{ overrides: typeof rows }>(`/datasets/${dataset}/project-image-sources${profileId ? `?profileId=${encodeURIComponent(profileId)}` : ''}`)
      .then((value) => { if (active) setRows(value.overrides); }).catch(() => { /* Older services have no exact addresses; creation still validates server-side. */ });
    return () => { active = false; };
  }, [dataset, profileId]);
  if (!rows.length) return null;
  return <details className="project-image-addresses"><summary>{t('Saved project image addresses')} · {rows.length}</summary><p>{t('These addresses are copied into this new task when it is queued. Editing them later does not change existing jobs.')}</p>
    {rows.map((row) => <div className="project-image-address" key={row.source}><code>{row.source}</code><code>→ {row.target}</code></div>)}
  </details>;
}
