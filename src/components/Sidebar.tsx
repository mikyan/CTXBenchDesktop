import {
  Boxes,
  DatabaseZap,
  LibraryBig,
  FlaskConical,
  Gauge,
  Settings2,
  ShieldCheck,
} from "lucide-react";
import type { Page } from "../app-types";
import { useI18n } from "../i18n";
import { version } from "../../package.json";

const navItems: Array<{ id: Page; label: string; icon: typeof Gauge }> = [
  { id: "overview", label: "Overview", icon: Gauge },
  { id: "experiments", label: "Experiments", icon: FlaskConical },
  { id: "datasets", label: "Datasets", icon: LibraryBig },
  { id: "knowledge", label: "Knowledge", icon: DatabaseZap },
  { id: "constraints", label: "Constraints", icon: ShieldCheck },
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
        <div className="nav-label">{t("BENCHMARKING")}</div>
        {navItems.map((item) => {
          const Icon = item.icon;
          return (
            <div key={item.id}>{item.id === "datasets" && <div className="nav-label">{t("PREPARATION")}</div>}<button
              type="button"
              key={item.id}
              className={`nav-item ${page === item.id ? "selected" : ""}`}
              aria-current={page === item.id ? "page" : undefined}
              onClick={() => onNavigate(item.id)}
            >
              <Icon size={17} />
              <span>{t(item.label)}</span>
            </button></div>
          );
        })}
      </nav>

      <div className="sidebar-bottom">
        <button type="button" className={`nav-item ${page === "infrastructure" ? "selected" : "ghost"}`} aria-current={page === "infrastructure" ? "page" : undefined} onClick={() => onNavigate("infrastructure")}>
          <Settings2 size={17} />
          <span>{t("Settings")}</span>
        </button>
        <div className="runtime-card">
          <div className="runtime-row">
            <strong>{t("Local runtime")}</strong>
            <span className="version">v{version}</span>
          </div>
          <p>{t("Private by default. No telemetry.")}</p>
        </div>
      </div>
    </aside>
  );
}
