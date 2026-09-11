import { useId, useRef } from 'react';
import { useI18n } from '../i18n';

export function PatchFileImport({ label, content, onFile }: { label: string; content: string; onFile: (file: File) => void }) {
  const { t } = useI18n();
  const input = useRef<HTMLInputElement>(null);
  const statusId = useId();
  return <div className="patch-file-import">
    <button type="button" className="button secondary" aria-describedby={statusId} onClick={() => input.current?.click()}>{t(label)}</button>
    <input ref={input} type="file" accept=".patch,.diff,.txt" hidden aria-label={t(label)} onChange={(event) => {
      const file = event.currentTarget.files?.[0];
      event.currentTarget.value = '';
      if (file && !event.currentTarget.matches(':disabled')) onFile(file);
    }} />
    <p id={statusId} role="status">{t(content.trim() ? 'Patch text is present in the editor. It may be imported or edited; the current text is what will be saved.' : 'No patch text yet. You may type it above or import a patch file.')}</p>
    <p>{t('Importing replaces the current patch text. Cancelling or a read error keeps the existing text.')}</p>
  </div>;
}
