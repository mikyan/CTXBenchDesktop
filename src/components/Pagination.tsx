import { pageWindow } from "../domain/pagination";
import { useI18n } from "../i18n";

export function Pagination({ total, page, size = 50, onChange }: { total: number; page: number; size?: number; onChange: (page: number) => void }) {
  const { t } = useI18n();
  const window = pageWindow(total, page, size);
  return <div className="toolbar" aria-label={t("Pagination")}>
    <span>{t("{start}–{end} of {total}", { start: total ? window.start + 1 : 0, end: window.end, total })}</span>
    <button className="button secondary" disabled={!window.page} onClick={() => onChange(window.page - 1)}>{t("Previous")}</button>
    <span>{window.page + 1} / {window.pages}</span>
    <button className="button secondary" disabled={window.page + 1 >= window.pages} onClick={() => onChange(window.page + 1)}>{t("Next")}</button>
  </div>;
}
