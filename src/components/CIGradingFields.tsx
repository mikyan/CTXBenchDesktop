import { useEffect, useState } from 'react';
import { useI18n } from '../i18n';
import { workerRequest } from '../lib/desktop';
import type { CITest } from '../lib/dataset-authoring';
import { FormError } from './Dialogs';

interface Connection { id: string; document: { name: string; provider: string; apiUrl: string; repository: string; workflow: string }; credentialConfigured: boolean }
export const defaultCITest = (): CITest => ({ connectionId: '', requiredJobs: [], reportArtifact: '', minTests: 1, timeoutMinutes: 30, allowRemoteExecution: false });

export function CIGradingFields({ value, onChange }: { value: CITest; onChange: (value: CITest) => void }) {
  const { t } = useI18n();
  const [connections, setConnections] = useState<Connection[]>([]);
  const [draft, setDraft] = useState({ name: '', provider: 'github-actions', apiUrl: 'https://api.github.com', repository: '', workflow: 'ci.yml' });
  const [token, setToken] = useState(''); const [busy, setBusy] = useState(false); const [error, setError] = useState(''); const [status, setStatus] = useState('');
  const selected = connections.find((row) => row.id === value.connectionId);
  const refresh = async () => setConnections(await workerRequest<Connection[]>('/ci/connections'));
  useEffect(() => { let active = true; void workerRequest<Connection[]>('/ci/connections').then((rows) => { if (active) setConnections(rows); }).catch(() => { if (active) setError('CI configuration requires the matching newer evaluation service. Update application images first.'); }); return () => { active = false; }; }, []);
  const run = async (action: () => Promise<void>) => { setBusy(true); setError(''); setStatus(''); try { await action(); } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); } finally { setBusy(false); } };
  const change = (patch: Partial<CITest>) => onChange({ ...value, ...patch });
  return <fieldset disabled={busy} className="ci-grading-fields"><legend>{t('CI pipeline grading')}</legend>
    <p>{t('The Agent still codes in Docker. Grading uploads only the candidate code to a dedicated evaluation branch and triggers the selected remote workflow. Required jobs must all pass. Workflow skips, cancellations and platform errors are not test passes.')}</p>
    <label>{t('CI platform connection')}<select value={value.connectionId} onChange={(e) => { change({ connectionId: e.target.value, allowRemoteExecution: false }); setToken(''); setStatus(''); }}><option value="">{t('Select a connection')}</option>{connections.map((row) => <option key={row.id} value={row.id}>{row.document.name} · {row.document.repository} · {row.id.slice(0, 8)}</option>)}</select></label>
    <button type="button" className="text-button" onClick={() => void run(refresh)}>{t('Refresh connections')}</button>
    <details><summary>{t('Add platform connection / new version')}</summary>
      <p>{t('Connections are immutable versions shared by cases. Changing an endpoint creates a new version and requires a separately configured token; existing experiments keep their original version.')}</p>
      <label>{t('Connection name')}<input value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} /></label>
      <label>{t('CI platform')}<select value={draft.provider} onChange={(e) => setDraft({ ...draft, provider: e.target.value, apiUrl: e.target.value === 'github-actions' ? 'https://api.github.com' : '' })}><option value="github-actions">GitHub Actions / Enterprise</option><option value="http-ci">{t('Company HTTP CI gateway')}</option></select></label>
      <label>{t('Platform API base URL')}<input value={draft.apiUrl} placeholder="https://git.company.example/api/v3" onChange={(e) => setDraft({ ...draft, apiUrl: e.target.value })} /></label>
      <label>{t('CI repository (owner/name)')}<input value={draft.repository} placeholder="team/backend-bench" onChange={(e) => setDraft({ ...draft, repository: e.target.value })} /></label>
      <label>{t('Workflow filename / pipeline ID')}<input value={draft.workflow} placeholder="ci.yml" onChange={(e) => setDraft({ ...draft, workflow: e.target.value })} /></label>
      <p>{t(draft.provider === 'github-actions' ? 'GitHub: use the same repository as the case baseline. The workflow must exist at that commit and on the default branch, be enabled and support workflow_dispatch. Use a test-only repository without deployment workflows or production secrets.' : 'Company gateway: implement the CTXBench HTTP CI protocol (resolve, submit, poll, report and cancel). A raw Jenkins or other platform URL will not work without an adapter. See docs/ci-platform-adapter.md in the source repository.')}</p>
      <button type="button" className="button secondary" onClick={() => void run(async () => { const record = await workerRequest<Connection>('/ci/connections', 'POST', draft); await refresh(); change({ connectionId: record.id, allowRemoteExecution: false }); setToken(''); setStatus('Connection saved. No code was uploaded and no workflow was triggered.'); })}>{t('Save connection version')}</button>
    </details>
    {selected && <details><summary>{t('Platform token (evaluation service only)')} · {t(selected.credentialConfigured ? 'Configured' : 'Not configured')}</summary>
      <p>{t(selected.document.provider === 'github-actions' ? 'GitHub tokens need repository Contents read/write and Actions read/write. The token is kept only in evaluation-service memory, never sent to the Agent or saved with the case. Re-enter it after the service restarts.' : 'Use a token issued for this company gateway. It stays only in evaluation-service memory, is never sent to the Agent, and must be re-entered after the service restarts.')}</p>
      <label>{t('CI access token')}<input type="password" autoComplete="off" value={token} onChange={(e) => setToken(e.target.value)} /></label>
      <button type="button" className="button secondary" disabled={!token} onClick={() => void run(async () => { await workerRequest(`/ci/connections/${selected.id}/credential`, 'POST', { token }); setToken(''); await refresh(); setStatus('Platform token configured for this session.'); })}>{t('Set platform token')}</button>
      <button type="button" className="text-button" disabled={!selected.credentialConfigured} onClick={() => void run(async () => { await workerRequest(`/ci/connections/${selected.id}/credential`, 'POST', { token: '' }); setToken(''); await refresh(); })}>{t('Clear platform token')}</button>
    </details>}
    <label>{t('Required job names (one per line)')}<textarea rows={3} value={value.requiredJobs.join('\n')} placeholder={'build\ntest'} onChange={(e) => change({ requiredJobs: e.target.value.split('\n') })} /></label>
    <p>{t('Use exact job display names, including matrix suffixes. A GitHub job is not a unit-test case. Leave the artifact field blank for gate-only grading; test counts will be unknown, not zero.')}</p>
    <label>{t('JUnit report artifact name (optional)')}<input value={value.reportArtifact} placeholder="test-results" onChange={(e) => change({ reportArtifact: e.target.value })} /></label>
    {value.reportArtifact && <label>{t('Minimum executed tests')}<input type="number" min={1} max={1000000} value={value.minTests} onChange={(e) => change({ minTests: Number(e.target.value) })} /></label>}
    <label>{t('CI wait timeout (minutes)')}<input type="number" min={1} max={1440} value={value.timeoutMinutes} onChange={(e) => change({ timeoutMinutes: Number(e.target.value) })} /></label>
    <p>{t('Optional JUnit reports show total, passed, failed, error and skipped tests. Missing reports, zero executed tests or fewer than the configured minimum stop grading instead of passing silently.')}</p>
    <label className="check-line"><input type="checkbox" checked={value.allowRemoteExecution} onChange={(e) => change({ allowRemoteExecution: e.target.checked })} />{t('I authorize uploading candidate code and running CI on this platform, which may consume CI quota. I have checked repository visibility, secrets, runners and deployment triggers.')}</label>
    {status && <p role="status">{t(status)}</p>}{error && <FormError>{t(error)}</FormError>}
  </fieldset>;
}
