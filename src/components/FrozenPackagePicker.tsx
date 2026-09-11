import { useId } from 'react';
import type { KnowledgeArtifact, TaskSummary } from '../domain/types';
import { useI18n } from '../i18n';

export function matchingPackages(task: Pick<TaskSummary, 'repository' | 'baseCommit'>, artifacts: KnowledgeArtifact[]) {
  return artifacts.filter(item => item.repository === task.repository && item.commit === task.baseCommit);
}

export function FrozenPackagePicker({ tasks, artifacts, values, onChange, loading, failed, onRefresh, onImport }: {
  tasks: TaskSummary[]; artifacts: KnowledgeArtifact[]; values: Record<string, string>;
  onChange: (values: Record<string, string>) => void; loading?: boolean; failed?: boolean;
  onRefresh?: () => void; onImport: () => void;
}) {
  const { t } = useI18n(); const description = useId();
  return <fieldset className="frozen-package-picker"><legend>{t('Frozen knowledge packages')}</legend>
    <p id={description}>{t('Only ready packages with the same repository and exact baseline commit can be selected. Packages for another commit cannot be reused.')}</p>
    {loading ? <p role="status">{t('Loading knowledge packages…')}</p> : failed ? <p role="alert" className="form-error">{t('Could not refresh knowledge packages. The list may be out of date; retry before selecting a package.')}</p> : null}
    {tasks.map(task => {
      const matching = matchingPackages(task, artifacts); const ready = matching.filter(item => item.status === 'ready');
      const emptyReason = !artifacts.length ? 'No knowledge packages have been imported or generated yet.'
        : !matching.length ? 'No package matches this repository and baseline commit.'
        : 'Matching packages are still generating or invalid. Wait for generation to finish, or import a ready package.';
      return <div key={task.id}>
        <label>{task.id}<select aria-describedby={description} disabled={loading || failed} value={values[task.id] ?? ''} onChange={event => onChange({ ...values, [task.id]: event.target.value })}>
          <option value="">{t('Select matching package')}</option>
          {ready.map(item => <option key={item.id} value={item.id}>{item.source} · {item.id.slice(0, 16)} · {item.files} {t('files')}</option>)}
        </select></label>
        {!loading && !failed && !ready.length && <aside className="wizard-notice"><p>{t(emptyReason)}</p><dl className="review-grid"><div><dt>{t('Required repository')}</dt><dd>{task.repository}</dd></div><div><dt>{t('Required baseline commit')}</dt><dd><code>{task.baseCommit}</code></dd></div></dl></aside>}
      </div>;
    })}
    {onRefresh && <button type="button" className="button secondary" disabled={loading} onClick={onRefresh}>{t('Refresh knowledge packages')}</button>}
    <button type="button" className="button secondary" onClick={onImport}>{t('Import a matching package')}</button>
    <p>{t('Import opens above this experiment and keeps its draft. After import, select the package yourself. To generate one first, use Knowledge → Generate context before starting a new experiment.')}</p>
  </fieldset>;
}
