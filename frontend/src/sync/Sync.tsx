import { Fragment, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useOutletContext } from 'react-router-dom';
import { apiFetch, ApiError } from '../api/client';
import type { AuthUser, SyncRun } from '../api/types';
import RunResults from './RunResults';
import './sync.css';

export default function Sync() {
  const user = useOutletContext<AuthUser>();
  const client = useQueryClient();
  const [expanded, setExpanded] = useState<number[]>([]);
  const runs = useQuery({
    queryKey: ['sync', 'runs'],
    queryFn: async ({ signal }): Promise<SyncRun[]> => (await apiFetch('/api/sync/runs?limit=20', { signal })).json(),
    refetchInterval: 5000,
  });
  const start = useMutation({
    mutationFn: async () => { await apiFetch('/api/sync/runs', { method: 'POST' }); },
    onSettled: () => client.invalidateQueries({ queryKey: ['sync'] }),
  });
  const items = Array.isArray(runs.data) ? runs.data : [];
  const running = items.some(run => run.status === 'running');
  const startError = start.error instanceof ApiError && start.error.status === 409 ? 'A sync is already running. History will refresh automatically.'
    : start.error instanceof ApiError && start.error.status === 503 ? 'Collection is unavailable. Ask an administrator to check the collector configuration.'
    : 'Unable to start sync. Please try again.';
  return <section className="sync-page"><div className="sync-heading"><div><h1>Sync</h1><p>Last 20 runs · refreshes every 5 seconds</p></div>
    <div className="sync-actions"><button className="secondary" disabled={runs.isFetching} onClick={() => void client.invalidateQueries({ queryKey: ['sync'] })}>Refresh</button>
      {user.is_admin && <button disabled={start.isPending || running} onClick={() => start.mutate()}>{start.isPending ? 'Starting…' : running ? 'Sync running' : 'Sync now'}</button>}</div>
    </div>
    {start.isSuccess && <p role="status">Sync requested. Progress appears below.</p>}
    {start.isError && <p role="alert">{startError}</p>}
    {runs.isError && <p role="alert">Unable to {runs.data ? 'refresh' : 'load'} sync history. {runs.data && 'Showing the last received runs.'} <button onClick={() => void runs.refetch()}>Retry history</button></p>}
    {runs.isPending ? <p role="status">Loading sync history…</p> : items.length === 0 && !runs.isError ? <p>No sync runs yet.</p> : items.length > 0 && <div className="sync-scroll"><table className="sync-table">
      <thead><tr><th>Run</th><th>Started</th><th>Trigger</th><th>Status</th><th>Instances</th><th>Duration</th></tr></thead>
      <tbody>{items.map(run => {
        const open = expanded.includes(run.id);
        const seconds = Math.max(0, Math.floor(((run.finished_at ? Date.parse(run.finished_at) : runs.dataUpdatedAt) - Date.parse(run.started_at)) / 1000));
        return <Fragment key={run.id}><tr>
          <td><button className="secondary" aria-expanded={open} aria-controls={`run-${run.id}`} onClick={() => setExpanded(previous => open ? previous.filter(id => id !== run.id) : [...previous, run.id])}>Run #{run.id}</button></td>
          <td><time dateTime={run.started_at} title={run.started_at}>{new Date(run.started_at).toLocaleString()}</time></td>
          <td>{run.trigger}</td><td><span className={`sync-status sync-${run.status}`}>{run.status}</span></td><td>{run.instances_seen}</td>
          <td>{Math.floor(seconds / 60)}m {seconds % 60}s{!run.finished_at && ' (ongoing)'}</td>
        </tr>{open && <tr id={`run-${run.id}`}><td colSpan={6}><RunResults id={run.id} /></td></tr>}</Fragment>;
      })}</tbody>
    </table></div>}
  </section>;
}
