import { Bell, CircleHelp, Languages, Search } from "lucide-react";
import { useI18n } from "../i18n";

export function Topbar({ runtime }: { runtime: "desktop" | "mock" }) {
  const { locale, setLocale, t } = useI18n();
  return (
    <div className="topbar" data-tauri-drag-region>
      <div className="breadcrumb" data-tauri-drag-region>
        {t("Local workspace")} <span>/</span> {t("Benchmark lab")}
      </div>
      <div className="topbar-actions">
        <label className="command-search">
          <Search size={14} />
          <input aria-label={t("Search")} placeholder={t("Search runs, repos, tasks")} />
          <kbd>⌘ K</kbd>
        </label>
        <span className={`runtime-mode ${runtime}`}>
          <span /> {runtime === "mock" ? t("Mock adapter") : t("WSL worker")}
        </span>
        <div className="language-switcher" role="group" aria-label={t("Language")}>
          <Languages size={14} aria-hidden="true" />
          <button type="button" className={locale === "en" ? "selected" : ""} aria-pressed={locale === "en"} title={t("English")} onClick={() => setLocale("en")}>EN</button>
          <button type="button" className={locale === "zh-CN" ? "selected" : ""} aria-pressed={locale === "zh-CN"} title={t("Chinese")} onClick={() => setLocale("zh-CN")}>中</button>
        </div>
        <button type="button" className="icon-button" aria-label={t("Help")}><CircleHelp size={17} /></button>
        <button type="button" className="icon-button notification" aria-label={t("Notifications")}><Bell size={17} /><span /></button>
        <div className="avatar" title={t("Local operator")}>LB</div>
      </div>
    </div>
  );
}
