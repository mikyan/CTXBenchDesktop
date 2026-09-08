import { useEffect, useRef, useState } from "react";
import { useI18n } from "../i18n";
import { buildTiming, type ImageBuild } from "../lib/image-build";

function duration(ms: number) {
  const seconds = Math.floor(ms / 1000);
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}
const phaseLabels = { checking: "Checking the build environment", building: "Building image steps", pulling: "Resolving or pulling base images", installing: "Installing dependencies", exporting: "Exporting images" };

export function ImageBuildProgress({ build }: { build: ImageBuild }) {
  const { t } = useI18n();
  const [now, setNow] = useState(Date.now);
  const [follow, setFollow] = useState(true);
  const [copied, setCopied] = useState("");
  const log = useRef<HTMLPreElement>(null);
  useEffect(() => {
    if (build.status !== "running") return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [build.id, build.status]);
  useEffect(() => { if (follow && log.current) log.current.scrollTop = log.current.scrollHeight; }, [build.lines, follow]);
  const steps = Object.values(build.steps);
  const completed = steps.filter((step) => step.status === "done").length;
  const running = build.status === "running";
  const timing = buildTiming(build, now);
  // Do not show 100% until Compose actually exits successfully (export can take time).
  const determinate = !running || (steps.length > 0 && completed < steps.length);
  const value = build.status === "completed" ? 1 : completed;
  const max = build.status === "completed" ? 1 : Math.max(1, steps.length);
  const summary = build.status === "completed" ? "Image build completed" : build.status === "failed" ? "Image build failed" : phaseLabels[build.phase];
  return <section className={`image-build-progress ${build.status}`} aria-labelledby="image-build-title" aria-busy={running}>
    <div className="image-build-heading"><h3 id="image-build-title">{t("Image build progress")}</h3><span>{build.distribution}</span></div>
    <p role="status">{t(summary)}</p>
    <progress aria-label={t("Observed build steps")} max={max} value={determinate ? value : undefined} />
    <div className="image-build-metrics"><strong>{steps.length ? t("{done} / {total} observed steps completed", { done: completed, total: steps.length }) : t("Docker has not reported step counts; follow the live log below.")}</strong><span>{t("Elapsed: {time}", { time: duration(timing.elapsed) })}</span><span>{t("Last output: {time} ago", { time: duration(timing.silent) })}</span></div>
    <p className="image-build-hint">{t("Steps are discovered as Docker builds. This bar is not a time estimate; the total may increase.")}</p>
    {running && build.current && <pre className="image-build-current">{build.current}</pre>}
    {running && build.transfer && <div className="image-build-transfer"><label htmlFor="image-layer-progress">{t("Latest image layer transfer")} · {build.transfer.label}</label><progress id="image-layer-progress" aria-label={t("Latest image layer transfer")} value={build.transfer.downloaded} max={build.transfer.total} /></div>}
    {running && timing.silent >= 30_000 && <p className="setup-callout" role="status">{t("No new output for {time}. Some install steps are quiet; this alone does not mean the build is stuck. Check network and disk space if the wait continues.", { time: duration(timing.silent) })}</p>}
    <div className="image-build-log-toolbar"><strong>{t("Live build log (redacted)")}</strong><label><input type="checkbox" checked={follow} onChange={(event) => setFollow(event.target.checked)} />{t("Follow latest output")}</label><button className="button secondary" disabled={!build.lines.length} onClick={() => { void navigator.clipboard.writeText(build.lines.join("\n")).then(() => setCopied("Build log copied. Review before sharing."), () => setCopied("Clipboard access failed. Select and copy the visible text manually.")); }}>{t("Copy build log")}</button></div>
    <pre ref={log} className="image-build-log" tabIndex={0} aria-label={t("Live build log (redacted)")} onScroll={() => { const el = log.current; if (el && el.scrollHeight - el.scrollTop - el.clientHeight > 40) setFollow(false); }}>{build.lines.length ? build.lines.join("\n") : t("Waiting for Docker output…")}</pre>
    {build.omitted > 0 && <p className="image-build-hint">{t("Showing recent output only; {count} earlier lines were discarded to limit memory use.", { count: build.omitted })}</p>}
    <p className="image-build-hint">{t("You can leave this page and return while the app stays open. Build logs are kept only for this app session.")}</p>
    {copied && <p role="status">{t(copied)}</p>}
  </section>;
}
