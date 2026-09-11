import { useEffect, useState } from 'react';
import { useI18n } from '../i18n';
import { listLocalImages } from '../lib/desktop';

export function localImageChoices(values: string[]) {
  return [...new Set(values.filter((value) => value && value !== '<none>:<none>'))].sort();
}

/** Read-only discovery. Selecting an image never pulls, builds or changes a tag. */
export function LocalImageSelect({ distribution, value, onChange }: { distribution: string; value: string; onChange: (value: string) => void }) {
  const { t } = useI18n();
  const [images, setImages] = useState<string[]>([]);
  const [loading, setLoading] = useState(false), [error, setError] = useState('');
  const [revision, refresh] = useState(0);
  useEffect(() => {
    let active = true;
    setImages([]); setError('');
    if (!distribution.trim()) { setLoading(false); return; }
    setLoading(true);
    const timer = setTimeout(() => {
      void listLocalImages(distribution).then((result) => {
        if (!active) return;
        setImages(localImageChoices(result.images));
        if (result.error) setError('Could not list local Docker images. Manual entry is still available.');
      }).catch(() => { if (active) setError('Could not list local Docker images. Manual entry is still available.'); })
        .finally(() => { if (active) setLoading(false); });
    }, 300);
    return () => { active = false; clearTimeout(timer); };
  }, [distribution, revision]);
  return <div className="local-image-select">
    <label>{t('Choose an installed base image')}<select value={images.includes(value) ? value : ''} disabled={loading || !images.length} onChange={(event) => { if (event.target.value) onChange(event.target.value); }}>
      <option value="">{t(loading ? 'Listing local images…' : 'Select an image or enter its reference below')}</option>
      {images.map((image) => <option key={image} value={image}>{image}</option>)}
    </select></label>
    <button type="button" className="button secondary" disabled={loading || !distribution.trim()} onClick={() => refresh((revision) => revision + 1)}>{t('Refresh local images')}</button>
    <p>{t('Images in WSL: {distribution}. Choosing one does not download or modify it.', { distribution: distribution || t('Not selected') })}</p>
    {!distribution.trim() && <p>{t('Select an installed WSL distribution first.')}</p>}
    {error ? <p role="alert">{t(error)}</p> : !loading && distribution.trim() && images.length === 0 && <p>{t('No tagged local images found. Build or import the required images first, or enter a local image digest.')}</p>}
  </div>;
}
