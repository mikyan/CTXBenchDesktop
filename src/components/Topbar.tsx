import { Bell, CircleHelp, Languages, Search } from "lucide-react";
import { useState } from 'react';
import { useI18n } from "../i18n";
import { UserHelpDialog } from './UserHelpDialog';
import type { Page } from "../app-types";
import { pageLabels } from "../lib/navigation";
import { useDesktopConnection } from '../lib/use-desktop-connection';
import { IsolationNotice } from './IsolationNotice';

export function Topbar({ runtime, page = "overview" }: { runtime: "desktop" | "mock"; page?: Page }) {
  const { locale, setLocale, t } = useI18n();
  const connection = useDesktopConnection();
  const [help, setHelp] = useState(false);
  return (
    <><div className="topbar" data-tauri-drag-region>
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
        <button type="button" className="icon-button" aria-label={t('Help')} title={t('Help')} onClick={() => setHelp(true)}><CircleHelp size={17} /></button>
        <div className="avatar" title={t("Local operator")}>LB</div>
      </div>
    </div><IsolationNotice connection={connection} />{help && <UserHelpDialog onClose={() => setHelp(false)} />}</>
  );
}
