import { useEffect, useState } from 'react';
import { useI18n } from '../i18n';
import { workerRequest } from '../lib/desktop';
import { companyFeatureError, terminalOperatorJob, type OperatorJob } from '../lib/intranet';
import { OperatorJobPanel } from './OperatorJobPanel';

export function RemoteImagePull({ initialImage = '', onInstalled, compact = false }: { initialImage?: string; onInstalled?: (image: string) => void; compact?: boolean }) {
  const { t } = useI18n();
  const [reference, setReference] = useState(initialImage);
  const [confirmed, setConfirmed] = useState(false);
  const [job, setJob] = useState<OperatorJob>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => { setReference(initialImage); setConfirmed(false); }, [initialImage]);
  const active = busy || Boolean(job && !terminalOperatorJob(job.status));
  const pull = async () => {
    setBusy(true); setError('');
    try { setJob(await workerRequest<OperatorJob>('/intranet/operations/image-pull', 'POST', { image: reference.trim(), confirmed })); }
    catch (cause) { setError(companyFeatureError(cause)); }
    finally { setBusy(false); }
  };
  const body = <>
    <p>{t('Download an existing Linux amd64 image from Docker Hub or your company registry. Enter the full image reference, not a docker pull command. Existing local tags are reused, never replaced; use a new tag or digest for a newer version.')}</p>
    <label>{t('Remote image reference')}<input disabled={active} value={reference} placeholder="registry.company.example/team/image:1.0" onChange={(e) => { setReference(e.target.value); setConfirmed(false); }} /></label>
    <label className="check-line"><input type="checkbox" disabled={active} checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />{t('I trust this image source and allow the download and disk usage. Pulling does not run the image or call a model.')}</label>
    <button type="button" className="button secondary" disabled={active || !confirmed || !reference.trim()} onClick={() => void pull()}>{t('Pull image')}</button>
    <p>{t('The evaluation service must be running. Private registry login is separate from model API keys. If authentication is required, docker login and pull this image in the selected WSL distribution, then refresh local images. Docker Hub access is not required when a full company address is supplied.')}</p>
    {error && <p className="form-error" role="alert">{t(error)}</p>}
    {job && <OperatorJobPanel initial={job} controls onStatusChange={(value) => { if (terminalOperatorJob(value.status)) setJob((current) => current?.id === value.id && current.status !== value.status ? value : current); }} onCompleted={(value) => { if (value.result?.tag) onInstalled?.(value.result.tag); }} />}
  </>;
  return compact ? <details className="secondary-disclosure"><summary>{t('Pull an existing image')}</summary>{body}</details> : <section className="panel remote-image-pull"><h3>{t('Pull an existing image')}</h3>{body}</section>;
}
