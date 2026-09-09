import { useState } from 'react';
import { useI18n } from '../i18n';
import { buildFiles } from '../lib/intranet';
import { dependencyTemplates, guidedDockerfile, type GuidedRecipe, type RecipeFile } from '../lib/image-recipes';
import { RemoteImagePull } from './RemoteImagePull';

export function ImageRecipeGuide({ onApply }: { onApply: (recipe: GuidedRecipe) => void }) {
  const { t } = useI18n();
  const [step, setStep] = useState(0), [base, setBase] = useState(''), [name, setName] = useState('');
  const [commands, setCommands] = useState(''), [defaults, setDefaults] = useState('HOME=/home/ctxbench\nLANG=C.UTF-8');
  const [files, setFiles] = useState<RecipeFile[]>([]), [network, setNetwork] = useState<'none' | 'bridge'>('none');
  const [error, setError] = useState(''), [busy, setBusy] = useState(false);
  let preview = '', problem = '';
  try { preview = guidedDockerfile(commands, defaults, files); } catch (cause) { problem = (cause as Error).message; }
  return <section className="image-recipe-guide"><h3>{t('Build your image step by step')}</h3>
    <p>{t('Prepare a dependency-only image once and reuse it. The original image is never edited. Do not copy the repository, answers, hidden tests, API keys or login state into image layers.')}</p>
    <div className="section-tabs" role="group" aria-label={t('Image recipe steps')}>{['Choose a base', 'Install dependencies', 'Configure defaults', 'Review recipe'].map((label, index) => <button type="button" key={label} disabled={busy} className={index === step ? 'selected' : ''} aria-pressed={step === index} onClick={() => setStep(index)}>{index + 1}. {t(label)}</button>)}</div>
    {step === 0 && <>
      <label>{t('Adaptation name')}<input value={name} onChange={(e) => setName(e.target.value)} /></label>
      <label>{t('Local base image')}<input value={base} placeholder="registry.company.example/team/backend:1.0" onChange={(e) => setBase(e.target.value)} /></label>
      <RemoteImagePull initialImage={base} onInstalled={setBase} compact />
      <p>{t('Choose a Linux image that already has your language runtime. The templates below assume Debian/Ubuntu; Alpine, distroless and other systems need their own package commands. Pull the base first; the build pins the installed image ID.')}</p>
    </>}
    {step === 1 && <>
      <label>{t('Dependency command template')}<select value="" onChange={(e) => { const value = dependencyTemplates[e.target.value as keyof typeof dependencyTemplates]; if (value) { setCommands((old) => old ? old + '\n' + value : value); setNetwork('bridge'); } }}><option value="">{t('Append a template')}</option><option value="adapter">{t('Custom Agent prerequisites')}</option><option value="python">Python · venv + pytest</option><option value="node">Node.js · Agent CLI</option><option value="java">Java · Maven</option></select></label>
      <label>{t('Dependency and configuration commands')}<textarea rows={8} spellCheck={false} value={commands} onChange={(e) => setCommands(e.target.value)} /></label>
      <p>{t('Use shell commands, not FROM or RUN. Replace example packages and company registry URLs. Files uploaded in the next step are available under /opt/company before these commands run. Use pip --index-url, npm --registry, or Maven settings.xml for company sources.')}</p>
      <p>{t('Install packages under /opt/venv or system paths, never only under /workspace. Install your own Agent here, for example npm install -g your-package --registry=https://npm.company.example. Templates do not know your real package name.')}</p>
    </>}
    {step === 2 && <>
      <label>{t('Non-secret configuration files')}<input type="file" multiple disabled={busy} onChange={(e) => { const selected = Array.from(e.target.files ?? []); e.target.value = ''; setBusy(true); setError(''); void buildFiles(selected).then(setFiles).catch((cause) => setError(String(cause))).finally(() => setBusy(false)); }} /></label>
      {files.map((file) => <p key={file.path}><code>{file.path} → /opt/company/{file.path}</code></p>)}
      <label>{t('Image defaults (NAME=value, one per line)')}<textarea rows={5} spellCheck={false} value={defaults} onChange={(e) => setDefaults(e.target.value)} /></label>
      <p>{t('For example MY_AGENT_CONFIG=/opt/company/settings.json. To replace /etc configuration, add cp or sed commands in the previous step. Do not include tokens in JSON, Maven settings or environment defaults. API keys belong in Runtime environment, supplied at execution only.')}</p>
      <p>{t('The benchmark runs as UID 10001, even if the image default user is root. Keep Agent configuration readable by this user and HOME writable. /workspace is the fresh baseline, not an image configuration directory.')}</p>
    </>}
    {step === 3 && <>
      <pre className="image-recipe-preview">{`# FROM ${base || '<local base image>'} (pinned by the service)\n${preview}`}</pre>
      <label>{t('Build network')}<select value={network} onChange={(e) => setNetwork(e.target.value as 'none' | 'bridge')}><option value="none">{t('Offline (no build network)')}</option><option value="bridge">{t('Network enabled (use company sources in recipe)')}</option></select></label>
      <button type="button" className="button primary" disabled={busy || !base.trim() || !name.trim() || !!problem} onClick={() => onApply({ name, baseImage: base.trim(), dockerfile: preview, files, network })}>{t('Use recipe in the build form')}</button>
      <p>{t('Next: review and confirm the build below. After success copy the new image tag into the case test image or custom Agent image, run a small case, then export the image for your intranet. A successful build alone does not prove Agent or test compatibility.')}</p>
    </>}
    {step < 3 && <button type="button" className="button primary" disabled={busy} onClick={() => setStep(step + 1)}>{t('Next')}</button>}
    {(error || problem) && <p role="alert" className="form-error">{t(error || problem)}</p>}
  </section>;
}
