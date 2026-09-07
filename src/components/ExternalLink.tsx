import { useRef, useState, type MouseEvent, type ReactNode } from "react";
import { useI18n } from "../i18n";
import { externalLinks, isDesktopLink, openExternalLink, type ExternalDestination } from "../lib/external-links";

export function ExternalLink({ destination, children, className, label }: {
  destination: ExternalDestination; children: ReactNode; className?: string; label?: string;
}) {
  const { t } = useI18n();
  const [failed, setFailed] = useState(false);
  const [copyStatus, setCopyStatus] = useState("");
  const opening = useRef(false);
  const href = externalLinks[destination];
  const activate = async (event: MouseEvent<HTMLAnchorElement>) => {
    // Browser preview keeps normal links, including Ctrl-click and keyboard activation.
    if (!isDesktopLink() || event.button > 1) return;
    event.preventDefault();
    if (opening.current) return;
    opening.current = true; setFailed(false); setCopyStatus("");
    try { await openExternalLink(destination); }
    catch { setFailed(true); }
    finally { opening.current = false; }
  };
  const copy = async () => {
    try { await navigator.clipboard.writeText(href); setCopyStatus("Link copied."); }
    catch { setCopyStatus("Could not copy. Select the address and copy it manually."); }
  };
  return <span className="external-link">
    <a href={href} target="_blank" rel="noopener noreferrer" className={className} aria-label={label}
      onClick={(event) => void activate(event)} onAuxClick={(event) => void activate(event)}>{children}</a>
    {failed && <span className="external-link-error" role="alert">
      <span>{t("Could not open the default browser. Copy this address and open it manually.")}</span>
      <code>{href}</code>
      <button type="button" className="button secondary" onClick={() => void copy()}>{t("Copy link")}</button>
      <button type="button" className="button tertiary" onClick={() => setFailed(false)}>{t("Close")}</button>
      {copyStatus && <span role="status">{t(copyStatus)}</span>}
    </span>}
  </span>;
}
