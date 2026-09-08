import { Bell, CircleHelp, Languages, Search } from "lucide-react";
import { useI18n } from "../i18n";
import { ExternalLink } from "./ExternalLink";
import type { Page } from "../app-types";
import { pageLabels } from "../lib/navigation";

export function Topbar({ runtime, page = "overview" }: { runtime: "desktop" | "mock"; page?: Page }) {
  const { locale, setLocale, t } = useI18n();
  return (
    <div className="topbar" data-tauri-drag-region>
      <div className="breadcrumb" data-tauri-drag-region>
        {t("Local workspace")} <span>/</span> <strong>{t(pageLabels[page])}</strong>
      </div>
      <div className="topbar-actions">
        <span className={`runtime-mode ${runtime}`}>
          <span /> {runtime === "mock" ? t("Mock adapter") : t("WSL worker")}
        </span>
        <div className="language-switcher" role="group" aria-label={t("Language")}>
          <Languages size={14} aria-hidden="true" />
          <button type="button" className={locale === "en" ? "selected" : ""} aria-pressed={locale === "en"} title={t("English")} onClick={() => setLocale("en")}>EN</button>
          <button type="button" className={locale === "zh-CN" ? "selected" : ""} aria-pressed={locale === "zh-CN"} title={t("Chinese")} onClick={() => setLocale("zh-CN")}>中</button>
        </div>
        <ExternalLink className="icon-button" label={t("Help")} destination="help"><CircleHelp size={17} /></ExternalLink>
        <div className="avatar" title={t("Local operator")}>LB</div>
      </div>
    </div>
  );
}
