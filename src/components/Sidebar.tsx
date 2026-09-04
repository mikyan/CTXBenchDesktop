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

const navItems: Array<{ id: Page; label: string; icon: typeof Gauge }> = [
  { id: "overview", label: "Overview", icon: Gauge },
  { id: "experiments", label: "Experiments", icon: FlaskConical },
  { id: "knowledge", label: "Knowledge", icon: DatabaseZap },
  { id: "constraints", label: "Constraints", icon: ShieldCheck },
  { id: "infrastructure", label: "Infrastructure", icon: ServerCog },
];

export function Sidebar({ page, onNavigate }: { page: Page; onNavigate: (page: Page) => void }) {
  return (
    <aside className="sidebar">
      <div className="brand-block">
        <div className="brand-mark"><Boxes size={18} strokeWidth={2.4} /></div>
        <div className="brand-copy">
          <span>CTXBENCH</span>
          <small>DESKTOP</small>
        </div>
      </div>

      <nav className="main-nav" aria-label="Primary">
        <div className="nav-label">WORKSPACE</div>
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
              <span>{item.label}</span>
              {item.id === "experiments" && <em>3</em>}
            </button>
          );
        })}
      </nav>

      <div className="sidebar-bottom">
        <button type="button" className="nav-item ghost" onClick={() => onNavigate("infrastructure")}>
          <Settings2 size={17} />
          <span>Settings</span>
        </button>
        <div className="runtime-card">
          <div className="runtime-row">
            <span className="pulse-dot" />
            <strong>Local runtime</strong>
            <span className="version">v0.1</span>
          </div>
          <p>Private by default. No telemetry.</p>
        </div>
        <button type="button" className="collapse-button" aria-label="Collapse sidebar">
          <PanelLeftClose size={16} />
          <span>Collapse</span>
        </button>
      </div>
    </aside>
  );
}
