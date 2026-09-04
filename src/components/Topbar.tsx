import { Bell, CircleHelp, Search } from "lucide-react";

export function Topbar({ runtime }: { runtime: "desktop" | "mock" }) {
  return (
    <div className="topbar" data-tauri-drag-region>
      <div className="breadcrumb" data-tauri-drag-region>
        Local workspace <span>/</span> Benchmark lab
      </div>
      <div className="topbar-actions">
        <label className="command-search">
          <Search size={14} />
          <input aria-label="Search" placeholder="Search runs, repos, tasks" />
          <kbd>⌘ K</kbd>
        </label>
        <span className={`runtime-mode ${runtime}`}>
          <span /> {runtime === "mock" ? "Mock adapter" : "WSL worker"}
        </span>
        <button type="button" className="icon-button" aria-label="Help"><CircleHelp size={17} /></button>
        <button type="button" className="icon-button notification" aria-label="Notifications"><Bell size={17} /><span /></button>
        <div className="avatar" title="Local operator">LB</div>
      </div>
    </div>
  );
}
