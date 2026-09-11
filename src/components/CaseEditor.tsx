import { useEffect, useRef, useState } from 'react';
import { useI18n } from '../i18n';
import { workerRequest } from '../lib/desktop';
import { datasetRows, draftFromManifest, draftIssues, newDatasetDraft, type CustomTaskManifest, type TaskDraft } from '../lib/dataset-authoring';
import type { LibraryCaseDetail } from '../lib/case-library';
import { libraryError } from '../lib/case-library';
import { Modal, FormError } from './Dialogs';
import { EnvironmentFields, TaskFields } from './DatasetWizardFields';
import { DatasetSelfTest } from './DatasetSelfTest';

const editingSteps = ['Repository and environment', 'Task and tests', 'Review and save'] as const;

export function CaseEditor({ caseId, onClose, onSaved }: { caseId?: string; onClose: () => void; onSaved: () => void }) {
  const { t } = useI18n();
  const [draft, setDraft] = useState(newDatasetDraft);
  const [record, setRecord] = useState<LibraryCaseDetail>();
  const [official, setOfficial] = useState('');
  const [rawMode, setRawMode] = useState(false);
  const [step, setStep] = useState(0);
  const previousStep = useRef(step);
  const stepTitle = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    if (previousStep.current === step) return;
    previousStep.current = step;
    // Only navigation changes focus/scroll. Typing, imports and validation do not.
    stepTitle.current?.focus({ preventScroll: true });
    stepTitle.current?.scrollIntoView({ block: 'start', behavior: 'instant' });
  }, [step]);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(Boolean(caseId));
  const [error, setError] = useState('');
  useEffect(() => { let active = true;
    if (caseId) void workerRequest<LibraryCaseDetail>(`/library/cases/${caseId}`).then((item) => {
      if (!active) return;
      setRecord(item);
      if (item.benchmark === 'custom') {
        try {
          const next = draftFromManifest(item.name, [item.row as unknown as CustomTaskManifest]);
          setDraft({ ...next, tasks: next.tasks.map((task) => ({ ...task, override: null })) });
        } catch {
          // Preserve valid legacy definitions that the guided form cannot represent.
          setRawMode(true); setDraft({ ...newDatasetDraft(), name: item.name }); setOfficial(JSON.stringify(item.row, null, 2));
        }
      } else { setDraft({ ...newDatasetDraft(), name: item.name }); setOfficial(JSON.stringify(item.row, null, 2)); }
    }).catch((cause) => { if (active) setError(libraryError(cause)); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [caseId]);
  const custom = !rawMode && (!record || record.benchmark === 'custom');
  const issues = custom ? draftIssues(draft).map((issue) => issue.message === 'Give the dataset a name.' ? { ...issue, message: 'Give the case a name.' } : issue) : [];
  const change = (patch: Partial<TaskDraft>) => { setError(''); setDraft({ ...draft, tasks: [{ ...draft.tasks[0], ...patch }] }); };
  const upload = async (file: File | undefined, field: 'hiddenPatch' | 'goldPatch') => {
    if (!file || busy) return;
    if (file.size > 2_000_000) { setError('Patch files are limited to 2 MB.'); return; }
    setBusy(true); setError('');
    try { change({ [field]: await file.text() }); } catch { setError('Could not read the patch file.'); } finally { setBusy(false); }
  };
  const save = async () => {
    setError('');
    if (custom && issues.length) { setError(issues[0].message); return; }
    setBusy(true);
    try {
      const row = custom ? datasetRows(draft)[0] : JSON.parse(official);
      await workerRequest(caseId ? `/library/cases/${caseId}` : '/library/cases', caseId ? 'PUT' : 'POST', {
        name: draft.name, benchmark: record?.benchmark ?? 'custom', row, ...(record ? { expectedRevision: record.revision } : {}),
      });
      onSaved(); onClose();
    } catch (cause) { setError(libraryError(cause)); } finally { setBusy(false); }
  };
  const payload = custom && !issues.length ? JSON.stringify({ name: draft.name, benchmark: 'custom', rows: datasetRows(draft) }) : '';
  return <Modal title={t(caseId ? 'Edit evaluation case' : 'Create evaluation case')} busy={busy} warnOnClose onClose={onClose}>
    {loading ? <p role="status">{t('Loading…')}</p> : <>
      <p className="wizard-notice">{t('Save this case independently, then run it directly or add it to any matching dataset. Changes affect future snapshots only.')}</p>
      {record && <p>{t('Editing revision {revision}', { revision: record.revision })} · {t('Used by {count} datasets', { count: record.usedBy.length })}{record.usedBy.length > 0 && `: ${record.usedBy.map((item) => item.name).join(', ')}`}</p>}
      <fieldset disabled={busy || Boolean(caseId && !record)}>
        <label>{t('Case name')}<input autoFocus value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} /></label>
        {custom ? <>
          <div className="section-tabs" role="group" aria-label={t('Case editing steps')}>{editingSteps.map((label, index) => <button type="button" className={step === index ? 'selected' : ''} aria-pressed={step === index} key={label} onClick={() => setStep(index)}>{index + 1}. {t(label)}</button>)}</div>
          <h3 ref={stepTitle} tabIndex={-1}>{t(editingSteps[step])}</h3>
          {step === 0 && <EnvironmentFields value={draft.defaults} onChange={(defaults) => setDraft({ ...draft, defaults })} />}
          {step === 1 && <TaskFields standalone task={draft.tasks[0]} defaults={draft.defaults} onChange={change} onUpload={(file, field) => void upload(file, field)} />}
          {step === 2 && <>
            <dl className="review-grid"><div><dt>{t('Task ID')}</dt><dd>{draft.tasks[0].id}</dd></div><div><dt>{t('Repository')}</dt><dd>{draft.defaults.repository}</dd></div><div><dt>{t('Baseline')}</dt><dd>{draft.defaults.baseCommit}</dd></div></dl>
            {issues.length ? <ul>{issues.map((item, index) => <li key={index}>{t(item.message)}</li>)}</ul> : <p>{t('Definition ready. Saving does not execute tests or call a model.')}</p>}
            <DatasetSelfTest payload={payload} disabled={busy} />
          </>}
        </> : <>
          <p className="wizard-notice">{t(rawMode ? 'This existing definition uses fields the guided form cannot represent. Edit the complete JSON below; all original fields are preserved.' : 'This case uses an official grading protocol. Editing creates a local variant, not an unchanged official benchmark. Preserve all grading fields and matching baseline materials.')}</p>
          <OfficialCaseFields value={official} benchmark={record!.benchmark} onChange={setOfficial} />
          <details open={rawMode || undefined}><summary>{t('Grading definition (advanced, evaluator-only)')}</summary><p>{t('Includes hidden tests and reference fixes. Never copy this definition into a knowledge package or Agent prompt.')}</p><textarea aria-label={t('Case definition JSON')} rows={16} value={official} spellCheck={false} onChange={(e) => setOfficial(e.target.value)} /></details>
        </>}
      </fieldset>
      {custom && step < 2 ? <button className="button primary" disabled={busy} onClick={() => setStep(step + 1)}>{t('Next')}</button> : <button className="button primary" disabled={busy || Boolean(caseId && !record)} onClick={() => void save()}>{t(caseId ? 'Save case changes' : 'Save evaluation case')}</button>}
    </>}
    {error && <FormError>{t(error)}</FormError>}
  </Modal>;
}

function OfficialCaseFields({ value, benchmark, onChange }: { value: string; benchmark: string; onChange: (value: string) => void }) {
  const { t } = useI18n();
  let row: Record<string, unknown>;
  try { row = JSON.parse(value); if (!row || Array.isArray(row) || typeof row !== 'object') return null; } catch { return null; }
  const key = (...names: string[]) => names.find((name) => name in row) ?? names[0];
  const fields = benchmark === 'swebench' ? [
    ['Task ID', 'instance_id'], ['Repository (owner/name)', 'repo'], ['Baseline commit (40 characters)', 'base_commit'],
    ['Task prompt · agent-visible', 'problem_statement'], ['Test image', key('image', 'image_name')],
  ] : benchmark === 'custom' ? [
    ['Task ID', 'id'], ['Repository', 'repository'], ['Baseline commit (40 characters)', 'baseCommit'],
    ['Task prompt · agent-visible', 'prompt'], ['Test image', 'image'],
  ] : [
    ['Task ID', key('instance_id', 'id')], ['Repository (owner/name)', key('base_repo', 'repo', 'repository')],
    ['Baseline commit (40 characters)', key('base_sha', 'base_commit', 'baseCommit')],
    ['Task prompt · agent-visible', key('problem_description', 'problem_statement', 'task')], ['Test image', key('docker_image', 'image')],
  ];
  return <>{fields.map(([label, field]) => <label key={field}>{t(label)}{label.startsWith('Task prompt') ? <textarea rows={7} value={String(row[field] ?? '')} onChange={(e) => onChange(JSON.stringify({ ...row, [field]: e.target.value }, null, 2))} /> : <input value={String(row[field] ?? '')} onChange={(e) => onChange(JSON.stringify({ ...row, [field]: e.target.value }, null, 2))} />}</label>)}</>;
}
