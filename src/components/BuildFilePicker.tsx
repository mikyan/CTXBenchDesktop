import { useId, useRef } from 'react';
import { useI18n } from '../i18n';

/** The loaded recipe files, not the native input's reset value, are authoritative. */
export function BuildFilePicker({ label, count, busy = false, onSelect }: {
  label: string; count: number; busy?: boolean; onSelect: (files: File[]) => void;
}) {
  const { t } = useI18n();
  const input = useRef<HTMLInputElement>(null);
  const labelId = useId(), statusId = useId();
  return <div className="build-file-picker" role="group" aria-labelledby={labelId}>
    <strong id={labelId}>{t(label)}</strong>
    <div><button type="button" className="button secondary" disabled={busy} aria-describedby={statusId} onClick={() => input.current?.click()}>{t(count ? 'Replace loaded files' : 'Choose build files')}</button></div>
    <input ref={input} type="file" multiple hidden aria-label={t(label)} disabled={busy} onChange={(event) => {
      const selected = Array.from(event.currentTarget.files ?? []);
      event.currentTarget.value = ''; // Permit choosing an updated file with the same name.
      if (!busy && selected.length) onSelect(selected); // Cancelling keeps loaded contents.
    }} />
    <p id={statusId} role="status">{t(busy ? 'Reading files… Existing files stay until the new selection is ready.' : count ? '{count} files loaded. Choosing again replaces this list; cancelling keeps it.' : 'No build files loaded. Adding configuration files is optional.', { count })}</p>
  </div>;
}
