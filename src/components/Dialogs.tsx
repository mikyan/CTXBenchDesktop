import { useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { X } from "lucide-react";
import { useI18n } from "../i18n";

function keepTabInDialog(event: KeyboardEvent<HTMLDialogElement>) {
  if (event.key !== "Tab") return;
  event.stopPropagation();
  const dialog = event.currentTarget;
  const controls = Array.from(dialog.querySelectorAll<HTMLElement>("button, input, select, textarea, a[href], summary, [tabindex]"))
    .filter((node) => node.tabIndex >= 0 && !node.matches(":disabled") && node.getClientRects().length > 0 && node.closest("dialog") === dialog);
  const first = controls[0], last = controls.at(-1);
  if (!first) { event.preventDefault(); return; }
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
}

/** Native top-layer dialogs keep decisions visible even inside a scrolled form. */
export function Modal({ title, children, onClose, busy = false, warnOnClose = false }: {
  title: string; children: ReactNode; onClose: () => void; busy?: boolean; warnOnClose?: boolean;
}) {
  const { t } = useI18n();
  const ref = useRef<HTMLDialogElement>(null); const titleId = useId();
  const [edited, setEdited] = useState(false); const [discard, setDiscard] = useState(false);
  useEffect(() => { const dialog = ref.current!; dialog.showModal(); return () => dialog.close(); }, []);
  const close = () => { if (!busy) { if (warnOnClose && edited) setDiscard(true); else onClose(); } };
  return <dialog ref={ref} aria-labelledby={titleId} className="workbench-dialog" onKeyDown={keepTabInDialog} onCancel={(event) => { event.preventDefault(); event.stopPropagation(); close(); }}>
    <header><div><h2 id={titleId}>{title}</h2>{busy && <p className="dialog-busy" role="status">{t("Working — please wait before closing.")}</p>}</div>
      <button type="button" className="icon-button" aria-label={t("Close")} disabled={busy} title={busy ? t("Working — please wait before closing.") : t("Close")} onClick={close}><X size={18} /></button>
    </header>
    <div className="workbench-form" aria-busy={busy} onChangeCapture={() => setEdited(true)}>{children}</div>
    {discard && <ConfirmDialog title={t("Discard unsaved changes?")} description={t("Your edits in this form have not been submitted. Closing will discard them.")} cancelLabel={t("Keep editing")} confirmLabel={t("Discard and close")} onCancel={() => setDiscard(false)} onConfirm={onClose} />}
  </dialog>;
}

export function ConfirmDialog({ title, description, children, onCancel, onConfirm, confirmLabel, cancelLabel, disabled = false }: {
  title: string; description: string; children?: ReactNode; onCancel: () => void; onConfirm: () => void;
  confirmLabel: string; cancelLabel?: string; disabled?: boolean;
}) {
  const { t } = useI18n(); const ref = useRef<HTMLDialogElement>(null); const titleId = useId(); const descriptionId = useId();
  useEffect(() => {
    const previous = document.activeElement;
    const dialog = ref.current!; dialog.showModal();
    return () => { dialog.close(); if (previous instanceof HTMLElement && previous.isConnected) previous.focus({ preventScroll: true }); };
  }, []);
  return <dialog ref={ref} role="alertdialog" aria-modal="true" aria-labelledby={titleId} aria-describedby={descriptionId} className="confirmation-dialog"
    onKeyDown={keepTabInDialog} onCancel={(event) => { event.preventDefault(); event.stopPropagation(); onCancel(); }} onChange={(event) => event.stopPropagation()}>
    <h2 id={titleId}>{title}</h2><p id={descriptionId}>{description}</p>{children}
    <footer><button type="button" autoFocus className="button secondary" onClick={onCancel}>{cancelLabel ?? t("Cancel")}</button>
      <button type="button" className="button danger" disabled={disabled} onClick={onConfirm}>{confirmLabel}</button></footer>
  </dialog>;
}

/** Async errors move into view; ordinary success/progress notices remain inline. */
export function FormError({ children }: { children: string }) {
  const ref = useRef<HTMLParagraphElement>(null);
  useEffect(() => { ref.current?.focus(); ref.current?.scrollIntoView({ block: "nearest" }); }, [children]);
  return <p ref={ref} tabIndex={-1} className="form-error" role="alert">{children}</p>;
}
