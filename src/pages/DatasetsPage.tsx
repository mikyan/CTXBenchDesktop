import { useEffect, useState } from 'react';
import { Download, Plus, RefreshCw, Search } from 'lucide-react';
import type { BenchmarkKind, DashboardSnapshot } from '../domain/types';
import { useI18n } from '../i18n';
import { workerRequest } from '../lib/desktop';
import { benchmarkLabel } from '../lib/benchmark-labels';
import { emptyLibrary, libraryError, loadLibrary, selectionCases, type DatasetSnapshot, type LibrarySet } from '../lib/case-library';
import { pageWindow } from '../domain/pagination';
import { PageTitle } from '../components/shared';
import { Pagination } from '../components/Pagination';
import { SectionNav } from '../components/SectionNav';
import { StandardDatasetDownloads } from '../components/StandardDatasetDownloads';
import { StandardImageInstaller } from '../components/StandardImageInstaller';
import { CaseEditor } from '../components/CaseEditor';
import { SetEditor } from '../components/SetEditor';
import { DatasetSnapshotView } from '../components/DatasetSnapshotView';
import { FormError } from '../components/Dialogs';
import { IntranetWorkbench } from '../components/IntranetWorkbench';
import { DatasetWizard } from '../components/DatasetWizard';
import { DataDeleteDialog, type DeletionTarget } from '../components/DataDeleteDialog';

const views = [{ id: 'cases', label: 'Evaluation cases' }, { id: 'sets', label: 'Datasets' }, { id: 'downloads', label: 'Standard downloads' }, { id: 'self-test', label: 'Dataset self-test' }, { id: 'snapshots', label: 'Run snapshots' }] as const;
export function DatasetsPage({ snapshot, onImport, onExperiment, onGenerate, initialView = 'sets' }: {
  snapshot: DashboardSnapshot; onImport: (source?: BenchmarkKind) => void; onCreate?: () => void;
  onExperiment: (dataset: string, selection?: import('../lib/standard-images').ImageSelection) => void;
  onGenerate?: (source: string) => void; initialView?: 'cases' | 'sets';
}) {
  const { t } = useI18n();
  const [view, setView] = useState<typeof views[number]['id']>(initialView);
  const [library, setLibrary] = useState(emptyLibrary); const [ready, setReady] = useState(false);
  const [query, setQuery] = useState(''); const [page, setPage] = useState(0); const [error, setError] = useState('');
  const [loadError, setLoadError] = useState('');
  const [editCase, setEditCase] = useState<{ id?: string }>();
  const [editSet, setEditSet] = useState<{ record?: LibrarySet }>();
  const [installDataset, setInstallDataset] = useState<{ id: string; name: string }>();
  const [snapshots, setSnapshots] = useState<DatasetSnapshot[]>([]); const [selectedSnapshot, setSelectedSnapshot] = useState<string>();
  const [revision, setRevision] = useState(0);
  const [legacyDraft, setLegacyDraft] = useState(false);
  const [deleting, setDeleting] = useState<DeletionTarget>();
  const [notice, setNotice] = useState('');
  const imports = (snapshot.datasets ?? []).map((item) => item.id).join(',');
  const refresh = () => setRevision((current) => current + 1);
  useEffect(() => { let active = true; setError(''); setLoadError('');
    void loadLibrary().then((value) => { if (active) { setLibrary(value); setReady(true); } }).catch((cause) => { if (active) setLoadError(libraryError(cause)); });
    return () => { active = false; };
  }, [imports, revision]);
  useEffect(() => { let active = true;
    if (view === 'snapshots') void workerRequest<DatasetSnapshot[]>('/library/snapshots').then((items) => { if (active) setSnapshots(items.reverse()); }).catch((cause) => { if (active) setError(libraryError(cause)); });
    return () => { active = false; };
  }, [view, revision]);
  const cases = library.cases.filter((item) => `${item.name} ${item.taskId} ${item.repository}`.toLowerCase().includes(query.toLowerCase()));
  const sets = library.sets.filter((item) => item.name.toLowerCase().includes(query.toLowerCase()));
  const range = pageWindow(view === 'cases' ? cases.length : view === 'snapshots' ? snapshots.length : sets.length, page, 20);
  return <div className="page datasets-page">
    <PageTitle eyebrow={t('CASE LIBRARY')} title={t(initialView === 'cases' ? 'Evaluation cases' : 'Datasets')}
      description={t('Create cases independently. Compose datasets from existing cases. Freeze a snapshot automatically before each execution.')}
      actions={<><button className="button secondary" onClick={() => onImport()}><Download size={16} />{t('Import cases')}</button>
        <button className="button primary" disabled={initialView === 'sets' && !ready} onClick={() => initialView === 'cases' ? setEditCase({}) : setEditSet({})}><Plus size={16} />{t(initialView === 'cases' ? 'Create evaluation case' : 'Compose dataset')}</button></>} />
    <SectionNav label="Case library views" items={views} value={view} onChange={(value) => { setView(value); setQuery(''); setPage(0); }} />
    {error && <FormError>{t(error)}</FormError>}
    {notice && <p role="status" className="wizard-notice">{t(notice)}</p>}
    {loadError && <FormError>{`${t('Could not load existing cases. This is a library loading error, not an error in a new case. You can still open the case editor; saving requires a working evaluation service. Use Refresh to try loading again.')} ${t(loadError)}`}</FormError>}
    {!!library.importWarnings?.length && <aside className="wizard-notice" role="status"><strong>{t('Some imported datasets could not be loaded')}</strong><p>{t('Available cases and independent case creation are unaffected. No source data or historical results were deleted.')}</p>
      <ul>{library.importWarnings.map((warning) => <li key={warning.datasetId}>{warning.name} · {t(warning.message)}</li>)}</ul>
    </aside>}
    <div className="toolbar"><button className="button secondary" onClick={refresh}><RefreshCw size={16} />{t('Refresh')}</button>
      {(view === 'cases' || view === 'sets') && <label className="table-search"><Search size={16} /><input aria-label={t(view === 'cases' ? 'Search evaluation cases' : 'Search datasets')} placeholder={t(view === 'cases' ? 'Search evaluation cases' : 'Search datasets')} value={query} onChange={(e) => { setQuery(e.target.value); setPage(0); }} /></label>}
      {view === 'cases' && initialView !== 'cases' && <button className="button primary" onClick={() => setEditCase({})}>{t('Create evaluation case')}</button>}
      {view === 'sets' && initialView !== 'sets' && <button className="button primary" disabled={!ready} onClick={() => setEditSet({})}>{t('Compose dataset')}</button>}
    </div>
    {!ready && !loadError && <p role="status">{t('Loading…')}</p>}
    {view === 'cases' && <>
      {ready && !cases.length && <section className="panel empty-state"><h2>{t('No evaluation cases yet')}</h2><p>{t('Create a case or import standard cases first, then compose a dataset here.')}</p></section>}
      <div className="dataset-library">{cases.slice(range.start, range.end).map((item) => <article className="panel dataset-card" key={item.id}>
        <span className="panel-kicker">{benchmarkLabel(item.benchmark, t)} · v{item.revision}{item.modified && ` · ${t('Locally modified')}`}</span>
        <h2>{item.name}</h2><p>{item.repository}</p><code>{item.taskId} · {item.baseCommit.slice(0, 12)}</code>
        <details><summary>{t('Task prompt · agent-visible')}</summary><p className="task-prompt">{item.prompt}</p></details>
        <div className="form-actions"><button className="button secondary" onClick={() => setEditCase({ id: item.id })}>{t('Edit evaluation case')}</button>
          {onGenerate && <button className="text-button" onClick={() => onGenerate(item.id)}>{t('Generate context')}</button>}
          <button type="button" className="text-button danger-text" onClick={() => setDeleting({ kind: 'case', id: item.id })}>{t('Delete evaluation case')}</button>
          <button className="text-button" onClick={() => onExperiment(item.id)}>{t('New experiment')}</button>
          {item.benchmark !== 'custom' && <button className="text-button" onClick={() => setInstallDataset(item)}>{t('Install project images')}</button>}
        </div>
      </article>)}</div>
      <Pagination total={cases.length} page={page} size={20} onChange={setPage} />
    </>}
    {view === 'sets' && <>
      {ready && !sets.length && <section className="panel empty-state"><h2>{t('No datasets yet')}</h2><p>{t('Create a case or import standard cases first, then compose a dataset here.')}</p><button className="button secondary" onClick={() => setView('cases')}>{t('Evaluation cases')}</button></section>}
      <div className="dataset-library">{sets.slice(range.start, range.end).map((item) => <article className="panel dataset-card" key={item.id}>
        <span className="panel-kicker">{benchmarkLabel(item.benchmark, t)} · v{item.revision}</span><h2>{item.name}</h2><p>{item.count} {t('Tasks')} · {t('Editable composition')}</p>
        {!item.count && <p className="deletion-cohort-note">{t('Empty dataset: add cases before running again')}</p>}
        <details><summary>{t('Browse tasks')}</summary>{selectionCases(library, item).map((member) => <div className="collection-member" key={member.id}><span>{member.name} · v{member.revision}</span><button className="text-button" onClick={() => setEditCase({ id: member.id })}>{t('Edit evaluation case')}</button></div>)}</details>
        <div className="form-actions"><button className="button secondary" onClick={() => setEditSet({ record: item })}>{t('Edit dataset composition')}</button>
          <button type="button" className="text-button danger-text" onClick={() => setDeleting({ kind: 'set', id: item.id })}>{t('Delete dataset')}</button>
          {item.benchmark !== 'custom' && <button className="text-button" disabled={!item.count} onClick={() => setInstallDataset(item)}>{t('Install project images')}</button>}
          <button className="text-button" disabled={!item.count} onClick={() => onExperiment(item.id)}>{t('New experiment')}</button>
        </div>
      </article>)}</div>
      <Pagination total={sets.length} page={page} size={20} onChange={setPage} />
    </>}
    {view === 'downloads' && <><p>{t('Importing a standard dataset creates independent editable cases and an initial collection. Original imported definitions and historical results are preserved.')}</p><StandardDatasetDownloads benchmark="custom" onSelect={onImport} />
      <details className="panel"><summary>{t('Legacy draft import (advanced)')}</summary><p>{t('Restore previously saved multi-case drafts here. Importing adds their cases to the library and creates an initial dataset; existing cases and snapshots are not overwritten.')}</p><button className="button secondary" onClick={() => setLegacyDraft(true)}>{t('Open legacy draft importer')}</button></details>
    </>}
    {view === 'self-test' && <IntranetWorkbench section="Dataset self-test" />}
    {view === 'snapshots' && <section className="panel"><h2>{t('Run snapshots')}</h2><p>{t('Snapshots are created when work is queued. Editing the library never updates a running or historical snapshot.')}</p>
      {!snapshots.length && <p>{t('No run snapshots yet')}</p>}
      {snapshots.slice(range.start, range.end).map((item) => <div className="collection-member" key={item.id}><span>{item.name} · v{item.sourceRevision} · {item.members.length} {t('Tasks')}<small>{item.createdAt}</small></span><button className="text-button" onClick={() => setSelectedSnapshot(item.id)}>{t('View run snapshot')}</button></div>)}
      <Pagination total={snapshots.length} page={page} size={20} onChange={setPage} />
    </section>}
    {editCase && <CaseEditor caseId={editCase.id} onClose={() => setEditCase(undefined)} onSaved={refresh} />}
    {deleting && <DataDeleteDialog target={deleting} onClose={() => setDeleting(undefined)} onDeleted={() => { setNotice('Deleted. Historical snapshots and shared files were kept.'); refresh(); }} />}
    {legacyDraft && <DatasetWizard legacyImport onClose={() => setLegacyDraft(false)} onComplete={refresh} />}
    {editSet && <SetEditor collection={editSet.record} library={library} onClose={() => setEditSet(undefined)} onSaved={refresh} />}
    {selectedSnapshot && <DatasetSnapshotView id={selectedSnapshot} onClose={() => setSelectedSnapshot(undefined)} />}
    {installDataset && <StandardImageInstaller dataset={installDataset.id} name={installDataset.name} onClose={() => setInstallDataset(undefined)} onExperiment={(selection) => { onExperiment(installDataset.id, selection); setInstallDataset(undefined); }} />}
  </div>;
}
