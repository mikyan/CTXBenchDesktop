import { useEffect, useRef, useState } from 'react';
import { useI18n } from '../i18n';
import { saveText, workerRequest } from '../lib/desktop';
import { Modal } from './Dialogs';
import { FailureDetails, type FailureDiagnostic } from './FailureDetails';

export type LogScope = { experimentId: string } | { operationId: string } | { benchmarkRunId: string } | { runId: string };
export interface LogSession {
  id: string; mode: string; startedAt: string; updatedAt: string;
  state: 'streaming' | 'ended' | 'unavailable' | 'interrupted'; exitCode: number | null;
  error?: string; truncated: boolean; startOffset: number; endOffset: number;
  containerName?: string;
  source?: string; label?: string; sequence?: number; failure?: FailureDiagnostic; archiveVersion?: number;
}
export interface LogPage extends LogSession { content: string; nextOffset: number; hasMore: boolean; reset: boolean; pageOffset?: number }
export function logTail(text: string) {
  const tail = text.slice(-200_000);
  return /^[\uDC00-\uDFFF]/.test(tail) ? tail.slice(1) : tail;
}

export function logRequestFailure(cause: unknown) {
  const message = cause instanceof Error ? cause.message : String(cause);
  if (/^(?:Error: )?Select a valid experiment, preparation or run to view container logs\.$/.test(message)) {
    return { message: 'The evaluation service rejected this log request. Update matching service images, then refresh these logs. Saved evidence remains available; task execution is unchanged.', retry: false };
  }
  if (/^(?:Error: )?Not Found$/i.test(message)) {
    return { message: 'Live container logs require updated evaluation service images. Existing evidence files remain available.', retry: false };
  }
  return { message: 'Log connection lost; reconnecting. The task is not paused.', retry: true };
}

export function ContainerLogDialog({ scope, onClose }: { scope: LogScope; onClose: () => void }) {
  const { t } = useI18n();
  return <Modal title={t('Live container logs')} onClose={onClose}><ContainerLogViewer scope={scope} /></Modal>;
}

export function ContainerLogViewer({ scope }: { scope: LogScope }) {
  const { t, locale } = useI18n();
  const query = new URLSearchParams(scope).toString();
  const [sessions, setSessions] = useState<LogSession[]>([]);
  const [olderSessions, setOlderSessions] = useState<LogSession[]>([]);
  const [olderCursor, setOlderCursor] = useState<number | null>();
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [loadingPage, setLoadingPage] = useState(false);
  const [history, setHistory] = useState(false);
  const [historyOffset, setHistoryOffset] = useState(0);
  const [selection, setSelection] = useState('');
  const [current, setCurrent] = useState<LogPage>();
  const [text, setText] = useState('');
  const [paused, setPaused] = useState(false);
  const [follow, setFollow] = useState(true);
  const [error, setError] = useState('');
  const [actionError, setActionError] = useState('');
  const [connected, setConnected] = useState(false);
  const [revision, refresh] = useState(0);
  const cursor = useRef<{ query: string; id: string; offset?: number } | undefined>(undefined);
  const output = useRef<HTMLPreElement>(null);
  const activeQuery = useRef<string | undefined>(query);
  const loadedOlder = useRef(false);
  useEffect(() => { activeQuery.current = query; return () => { activeQuery.current = undefined; }; }, [query]);
  useEffect(() => { setSelection(''); setSessions([]); setOlderSessions([]); setOlderCursor(undefined); loadedOlder.current = false; setLoadingOlder(false); setHistory(false); setHistoryOffset(0); setCurrent(undefined); setText(''); setConnected(false); cursor.current = undefined; }, [query]);
  useEffect(() => {
    if (paused && !revision) return;
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    let request: AbortController;
    const poll = async () => {
      let retry = true;
      setLoadingPage(true);
      request = new AbortController();
      const timeout = setTimeout(() => request.abort(), 10000);
      try {
        const inventory = await workerRequest<{ sessions: LogSession[]; nextBefore?: number | null }>(`/container-logs?${query}`, 'GET', undefined, request.signal);
        if (!alive) return;
        setSessions(inventory.sessions);
        setOlderCursor((old) => !loadedOlder.current ? inventory.nextBefore ?? null : old);
        const failed = inventory.sessions.find((session) => session.failure);
        const newerAttempt = failed && inventory.sessions.some((session) => session.startedAt > (failed.failure?.failedAt ?? failed.startedAt) && (failed.failure?.failedAt || session.state === 'streaming'));
        const id = selection || (!newerAttempt && failed?.id) || inventory.sessions[0]?.id;
        if (id) {
          const same = cursor.current?.id === id && cursor.current?.query === query;
          const offset = history ? historyOffset : same ? cursor.current?.offset : undefined;
          const page = await workerRequest<LogPage>(`/container-logs/${encodeURIComponent(id)}${offset === undefined ? '' : `?offset=${offset}`}`, 'GET', undefined, request.signal);
          if (!alive) return;
          setText((previous) => history ? page.content : logTail((same && !page.reset ? previous : '') + page.content));
          cursor.current = { query, id, offset: page.nextOffset };
          setCurrent(page);
        } else {
          setCurrent(undefined); setText(''); cursor.current = undefined;
        }
        setError(''); setConnected(true);
      } catch (cause) {
        if (!alive) return;
        const failure = logRequestFailure(cause);
        setError(failure.message);
        retry = failure.retry; setConnected(false);
      } finally { clearTimeout(timeout); if (alive) setLoadingPage(false); }
      if (alive && !paused && !history && retry) timer = setTimeout(() => void poll(), 1000);
    };
    void poll();
    return () => { alive = false; clearTimeout(timer); request?.abort(); };
  }, [query, selection, paused, revision, history, historyOffset]);
  useEffect(() => { if (output.current) { if (history) output.current.scrollTop = 0; else if (follow) output.current.scrollTop = output.current.scrollHeight; } }, [text, follow, history]);
  const mode = (value: string) => t(({ preparation: 'Preparation and service diagnostics', solve: 'Coding Agent', 'generate-context': 'Knowledge generation', 'mine-constraints': 'Constraint mining', 'judge-constraints': 'Constraint judging', test: 'Project tests', evaluator: 'Official evaluator' } as Record<string, string>)[value] ?? value);
  const allSessions = [...sessions, ...olderSessions.filter((old) => !sessions.some((item) => item.id === old.id))];
  const loadOlder = async () => {
    if (!olderCursor) return;
    const requestedQuery = query;
    setLoadingOlder(true); setActionError('');
    try {
      const result = await workerRequest<{ sessions: LogSession[]; nextBefore?: number | null }>(`/container-logs?${query}&before=${olderCursor}`);
      if (requestedQuery !== activeQuery.current) return;
      loadedOlder.current = true;
      setOlderSessions((old) => [...old, ...result.sessions]); setOlderCursor(result.nextBefore ?? null);
    } catch { if (requestedQuery === activeQuery.current) setActionError('Could not load older log sources. Retry without restarting the task.'); }
    finally { if (requestedQuery === activeQuery.current) setLoadingOlder(false); }
  };
  const state = history ? 'Browsing saved log pages; task execution continues independently.' : paused ? 'Log refresh paused; the task keeps running.' : error ? '' : !connected ? 'Connecting to container logs…' : !current ? 'Waiting for a container to start. Cached work may not start a new container.' : current.state === 'streaming' ? 'Live · checking for new output every second' : current.state === 'interrupted' ? 'The service restarted; this earlier log stream is no longer live.' : current.state === 'unavailable' ? 'Container log collection is unavailable. Task execution is independent.' : 'Log stream ended';
  return <section className="container-log-viewer" aria-label={t('Live container logs')}>
    <p>{t('Preparation steps, original errors and container output. Viewing logs never changes task execution.')}</p>
    <FailureDetails diagnostic={current?.failure} />
    <label>{t('Container / stage')}<select value={selection} onChange={(event) => { setSelection(event.target.value); setHistoryOffset(0); cursor.current = undefined; refresh((value) => value + 1); }}>
      <option value="">{t('Follow latest failure or execution')}</option>
      {allSessions.map((session) => <option key={session.id} value={session.id}>{session.label ? t(session.label) : mode(session.mode)} · {new Date(session.startedAt).toLocaleTimeString(locale)} · {session.containerName ?? session.id.slice(0, 8)}</option>)}
    </select></label>
    {olderCursor && <button type="button" className="button secondary" disabled={loadingOlder} onClick={() => void loadOlder()}>{t('Load older log sources')}</button>}
    <div className="toolbar">
      <button type="button" className="button secondary" disabled={!current} onClick={() => { setHistory((old) => !old); setHistoryOffset(0); setSelection(current?.id ?? ''); cursor.current = undefined; refresh((value) => value + 1); }}>{t(history ? 'Return to live tail' : 'Read complete log from beginning')}</button>
      {!history && <button type="button" className="button secondary" onClick={() => { setPaused((value) => !value); refresh(0); }}>{t(paused ? 'Resume log refresh' : 'Pause log refresh')}</button>}
      <button type="button" className="button secondary" onClick={() => refresh((value) => value + 1)}>{t('Refresh logs now')}</button>
      {!history && <label className="checkbox-line"><input type="checkbox" checked={follow} onChange={(event) => setFollow(event.target.checked)} />{t('Auto-scroll logs')}</label>}
      <button type="button" className="button secondary" disabled={!text} onClick={() => { setActionError(''); void saveText(`container-${current?.id ?? 'log'}.txt`, text).catch(() => setActionError('Could not export the visible log window.')); }}>{t('Export visible logs')}</button>
    </div>
    {history && <div className="toolbar"><span>{t('Complete log · paged reading, not a truncated tail')} · {t('Character offset')}: {current?.pageOffset ?? historyOffset}</span>
      <button type="button" className="button secondary" disabled={loadingPage || historyOffset <= (current?.startOffset ?? 0)} onClick={() => { setHistoryOffset(Math.max(current?.startOffset ?? 0, historyOffset - 64000)); refresh((value) => value + 1); }}>{t('Previous log page')}</button>
      <button type="button" className="button secondary" disabled={loadingPage || !current?.hasMore} onClick={() => { setHistoryOffset(current?.nextOffset ?? 0); refresh((value) => value + 1); }}>{t('Next log page')}</button>
    </div>}
    <p role="status">{t(state)}{current?.exitCode != null && ` · ${t('Exit code')}: ${current.exitCode}`}</p>
    {(error || actionError) && <p role="alert" className="form-error">{t(error || actionError)}</p>}
    {current?.state === 'unavailable' && <p>{t('Log capture failed or was interrupted; check task status and saved evidence separately.')}</p>}
    {current?.updatedAt && <p className="container-log-time">{t('Last log activity')}: {new Date(current.updatedAt).toLocaleString(locale)}</p>}
    {current?.truncated && <p role="alert">{t('Earlier output is missing from this older log. It cannot be reconstructed by updating the application.')}</p>}
    {!history && <p>{t('This is the live tail. Use Read complete log from beginning to browse every saved page.')}</p>}
    <pre ref={output} className="log-view live-container-output" aria-label={t('Container output')} tabIndex={0} onScroll={(event) => {
      const element = event.currentTarget;
      if (element.scrollHeight - element.scrollTop - element.clientHeight > 32) setFollow(false);
    }}>{text || t('No output received yet. A quiet process is not necessarily stuck.')}</pre>
    <details><summary>{t('Log limits and debugging tips')}</summary><p>{t('New execution logs are archived from the beginning without automatic tail deletion. The page reads bounded chunks; exporting visible logs exports only the current window. Monitor disk space. Configured credentials are redacted; logs are never sent to Agents.')}</p>
      <p>{t('Programs and Docker may buffer output without a newline. Print complete lines; for Python use python -u or flush=True. Logs cannot show text that has not been flushed.')}</p>
      <p>{t('Capture failures and older missing logs cannot be repaired retroactively. Some official test details remain in evidence files.')}</p>
    </details>
  </section>;
}
