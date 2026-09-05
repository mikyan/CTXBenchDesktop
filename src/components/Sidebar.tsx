import {
  Boxes,
  DatabaseZap,
  FlaskConical,
  Gauge,
  PanelLeftClose,
  ServerCog,
  Settings2,
  ShieldCheck,
} from "lucide-react";
import type { Page } from "../app-types";
import { useI18n } from "../i18n";

const navItems: Array<{ id: Page; label: string; icon: typeof Gauge }> = [
  { id: "overview", label: "Overview", icon: Gauge },
  { id: "experiments", label: "Experiments", icon: FlaskConical },
  { id: "knowledge", label: "Knowledge", icon: DatabaseZap },
  { id: "constraints", label: "Constraints", icon: ShieldCheck },
  { id: "infrastructure", label: "Infrastructure", icon: ServerCog },
];

export function Sidebar({ page, onNavigate }: { page: Page; onNavigate: (page: Page) => void }) {
  const { t } = useI18n();
  return (
    <aside className="sidebar">
      <div className="brand-block">
        <div className="brand-mark"><Boxes size={18} strokeWidth={2.4} /></div>
        <div className="brand-copy">
          <span>CTXBENCH</span>
          <small>DESKTOP</small>
        </div>
      </div>

      <nav className="main-nav" aria-label={t("Primary")}>
        <div className="nav-label">{t("WORKSPACE")}</div>
        {navItems.map((item) => {
          const Icon = item.icon;
          return (
            <button
              type="button"
              key={item.id}
              className={`nav-item ${page === item.id ? "selected" : ""}`}
              onClick={() => onNavigate(item.id)}
            >
              <Icon size={17} />
              <span>{t(item.label)}</span>
            </button>
          );
        })}
      </nav>

      <div className="sidebar-bottom">
        <button type="button" className="nav-item ghost" onClick={() => onNavigate("infrastructure")}>
          <Settings2 size={17} />
          <span>{t("Settings")}</span>
        </button>
        <div className="runtime-card">
          <div className="runtime-row">
            <span className="pulse-dot" />
            <strong>{t("Local runtime")}</strong>
            <span className="version">v0.1</span>
          </div>
          <p>{t("Private by default. No telemetry.")}</p>
        </div>
      </div>
    </aside>
  );
}
