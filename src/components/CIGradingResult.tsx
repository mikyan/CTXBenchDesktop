import { useState } from 'react';
import { useI18n } from '../i18n';
import type { BenchmarkRun } from '../domain/types';

interface CIReceipt { provider?: string; repository?: string; branch?: string; commit?: string; remoteId?: string | number; status?: string; url?: string; attempt?: number }
interface CIGrade { gradingMode?: string; ci?: CIReceipt; requiredJobs?: { name: string; conclusion: string }[]; testCounts?: { total: number; passed: number; failures: number; errors: number; skipped: number } }
export function CIGradingResult({ run }: { run: BenchmarkRun }) {
  const { t } = useI18n(); const [copied, setCopied] = useState('');
  const grade = (run.grade ?? {}) as CIGrade;
  const ci = (run.ci ?? grade.ci) as CIReceipt | undefined;
  if (!ci && grade.gradingMode !== 'ci') return null;
  return <section className="panel ci-grading-result"><h3>{t('CI pipeline evidence')}</h3>
    <dl className="review-grid"><div><dt>{t('Platform')}</dt><dd>{ci?.provider} · {ci?.repository}</dd></div><div><dt>{t('Workflow status')}</dt><dd>{t(ci?.status ?? 'Unknown')} · #{ci?.remoteId ?? '—'} · {t('Attempt')} {ci?.attempt ?? '—'}</dd></div><div><dt>{t('Evaluation branch')}</dt><dd><code>{ci?.branch}</code></dd></div><div><dt>{t('Candidate commit')}</dt><dd><code>{ci?.commit ?? '—'}</code></dd></div></dl>
    {ci?.url && <><code className="ci-run-url">{ci.url}</code><button type="button" className="button secondary" onClick={() => void navigator.clipboard.writeText(ci.url!).then(() => setCopied('Link copied.')).catch(() => setCopied('Could not copy. Select the address and copy it manually.'))}>{t('Copy workflow URL')}</button>{copied && <p role="status">{t(copied)}</p>}</>}
    {grade.requiredJobs && <ul>{grade.requiredJobs.map((job) => <li key={job.name}>{job.name} · {t(job.conclusion === 'success' ? 'PASS' : 'FAIL')}</li>)}</ul>}
    {grade.testCounts ? <dl className="review-grid">{(['total', 'passed', 'failures', 'errors', 'skipped'] as const).map((key) => <div key={key}><dt>{t({ total: 'Total tests', passed: 'Passed tests', failures: 'Failed tests', errors: 'Test errors', skipped: 'Skipped tests' }[key])}</dt><dd>{grade.testCounts![key]}</dd></div>)}</dl> : <p>{t('Test counts unavailable — workflow job count is not unit-test count.')}</p>}
    <p>{t('Pausing stops local observation; the remote workflow may continue. Cancel requests remote cancellation when the matching run is known. Evaluation branches are retained for audit and are not deleted automatically.')}</p>
  </section>;
}
