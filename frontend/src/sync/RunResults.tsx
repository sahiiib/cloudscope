import { useQuery } from '@tanstack/react-query';
import { apiFetch } from '../api/client';
import type { SyncRunDetail } from '../api/types';

export default function RunResults({ id }: { id: number }) {
  const detail = useQuery({
    queryKey: ['sync', 'run', id],
    queryFn: async ({ signal }): Promise<SyncRunDetail> => (await apiFetch(`/api/sync/runs/${id}`, { signal })).json(),
    refetchInterval: query => query.state.data?.status === 'running' ? 5000 : false,
  });
  if (detail.isPending) return <p role="status">Loading run results…</p>;
  if (detail.isError && !detail.data) return <p role="alert">Unable to load run results. <button onClick={() => void detail.refetch()}>Retry results</button></p>;
  return <div>
    {detail.isError && <p role="alert">Results could not be refreshed. Showing the last received results.</p>}
    {detail.data.results.length === 0 ? <p>{detail.data.status === 'running' ? 'Results will appear as regions finish.' : 'No region results recorded.'}</p> :
      <table className="sync-table"><caption>Run {id}: account and region results</caption><thead><tr>
        <th>Provider</th><th>Account</th><th>Region</th><th>Status</th><th>Instances</th><th>Duration</th><th>Error</th>
      </tr></thead><tbody>{detail.data.results.map(result => <tr key={`${result.provider}/${result.account_id}/${result.region}`}>
        <td>{result.provider === 'aws' ? 'AWS' : 'Alibaba'}</td><td>{result.account_id}</td><td>{result.region}</td>
        <td><span className={`sync-status sync-${result.status}`}>{result.status}</span></td>
        <td>{result.instances_seen}</td><td>{(result.duration_ms / 1000).toFixed(1)}s</td><td className="sync-error">{result.error || '—'}</td>
      </tr>)}</tbody></table>}
  </div>;
}
