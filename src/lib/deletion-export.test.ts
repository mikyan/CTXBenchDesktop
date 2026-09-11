import { afterEach, describe, expect, it, vi } from 'vitest';
import { invoke } from '@tauri-apps/api/core';
import { createDemoSnapshot } from '../data/demo';
import { exportSnapshot } from './desktop';

vi.mock('@tauri-apps/api/core', () => ({ invoke: vi.fn(), Channel: vi.fn() }));
afterEach(() => { vi.unstubAllGlobals(); vi.resetAllMocks(); });

describe('exports after deleting data', () => {
  it.each(['json', 'csv', 'html'] as const)('%s refreshes rows and reports the reduced cohort', async (format) => {
    vi.stubGlobal('window', { __TAURI_INTERNALS__: {} });
    const stale = createDemoSnapshot(); stale.runtime = 'desktop';
    stale.runs[0].id = 'DELETED-RUN-ID';
    const fresh = { ...stale, runs: stale.runs.slice(1), experiments: stale.experiments.map((exp) => ({ ...exp, deletedResultGroups: 1, deletedResultRuns: 2 })) };
    let exported = '';
    vi.mocked(invoke).mockImplementation(async (command, args) => {
      if (command === 'worker_request') return fresh;
      if (command === 'save_export') { exported = (args as { content: string }).content; return; }
      throw Error('Unexpected command');
    });
    await exportSnapshot(stale, format);
    expect(invoke).toHaveBeenCalledWith('worker_request', { path: format === 'json' ? '/snapshot' : '/snapshot?compact=true', method: 'GET', body: null });
    expect(exported).not.toContain('DELETED-RUN-ID');
    expect(exported).toContain(format === 'json' ? 'deletedResultGroups' : format === 'csv' ? 'deleted_comparison_groups' : '1 comparison groups were deleted');
    if (format === 'json') expect(JSON.parse(exported).runs).toHaveLength(fresh.runs.length);
  });
  it('does not export stale results if refreshing fails', async () => {
    vi.stubGlobal('window', { __TAURI_INTERNALS__: {} });
    const stale = createDemoSnapshot(); stale.runtime = 'desktop';
    vi.mocked(invoke).mockRejectedValue(Error('Disconnected'));
    await expect(exportSnapshot(stale, 'csv')).rejects.toThrow('Disconnected');
    expect(invoke).toHaveBeenCalledTimes(1);
  });
});
