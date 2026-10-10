import { useQuery } from '@tanstack/react-query';
import { useLocation, useSearchParams } from 'react-router-dom';
import { apiFetch } from '../api/client';
import type { AccountSummary, InstanceFacets, InstancePage } from '../api/types';
import FacetFilter from './FacetFilter';
import InstanceTable from './InstanceTable';
import SearchInput from './SearchInput';
import './search.css';

const dimensions = [
  ['Provider', 'provider', 'providers'], ['Account', 'account_id', 'accounts'],
  ['Region', 'region', 'regions'], ['State', 'state', 'states'],
] as const;
const sorts = ['name', 'launch_time', 'last_observed', 'region', 'account'];
function positiveNumber(value: string | null, fallback: number, maximum: number) {
  const number = Number(value);
  return Number.isSafeInteger(number) && number > 0 && number <= maximum ? number : fallback;
}

export default function Search() {
  const location = useLocation();
  const [params, setParams] = useSearchParams();
  const page = positiveNumber(params.get('page'), 1, Number.MAX_SAFE_INTEGER);
  const pageSize = positiveNumber(params.get('page_size'), 50, 500);
  const rawSort = params.get('sort') || 'name';
  const sort = sorts.includes(rawSort.replace(/^-/, '')) ? rawSort : 'name';
  const filters = new URLSearchParams();
  for (const field of ['q', 'provider', 'account_id', 'region', 'state', 'tag']) {
    params.getAll(field).filter(value => field !== 'provider' || ['aws', 'alibaba'].includes(value)).forEach(value => filters.append(field, value));
  }
  filters.set('include_missing', String(params.get('include_missing') === 'true'));
  const filterQuery = filters.toString();
  const query = `${filterQuery}&sort=${encodeURIComponent(sort)}&page=${page}&page_size=${pageSize}`;
  const instances = useQuery({ queryKey: ['instances', query], queryFn: async ({ signal }): Promise<InstancePage> =>
    (await apiFetch(`/api/instances?${query}`, { signal })).json() });
  const facets = useQuery({ queryKey: ['instance-facets', filterQuery], queryFn: async ({ signal }): Promise<InstanceFacets> =>
    (await apiFetch(`/api/instances/facets?${filterQuery}`, { signal })).json() });
  const accounts = useQuery({ queryKey: ['accounts'], queryFn: async ({ signal }): Promise<AccountSummary[]> =>
    (await apiFetch('/api/accounts', { signal })).json() });
  function update(edit: (next: URLSearchParams) => void, resetPage = true) {
    setParams(previous => { const next = new URLSearchParams(previous); edit(next); if (resetPage) next.delete('page'); return next; });
  }
  const names = Object.fromEntries((Array.isArray(accounts.data) ? accounts.data : []).map(account => [account.account_id, account.name]));
  const total = instances.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / pageSize));
  return <section className="search-page"><h1>Search</h1><p>Find instances across your cloud accounts.</p>
    <SearchInput revision={location.key} value={params.get('q') || ''} onChange={value => update(next => { if (value) next.set('q', value); else next.delete('q'); })} />
    <div className="search-filters">{dimensions.map(([label, field, facet]) => <FacetFilter key={field} label={label}
      options={facets.data?.[facet] ?? []} selected={params.getAll(field)} names={field === 'account_id' ? names : undefined}
      onChange={(value, checked) => update(next => {
        const values = next.getAll(field).filter(item => item !== value);
        next.delete(field); [...values, ...(checked ? [value] : [])].forEach(item => next.append(field, item));
      })} />)}
      <label className="missing-toggle"><input type="checkbox" checked={params.get('include_missing') === 'true'} onChange={event => update(next => next.set('include_missing', String(event.target.checked)))} />Show terminated/missing</label>
      <button className="secondary" onClick={() => setParams({})}>Clear filters</button>
    </div>
    {facets.isError && <p role="alert">Unable to load filter counts. <button onClick={() => void facets.refetch()}>Retry filters</button></p>}
    {instances.isPending ? <p role="status">Loading instances…</p> : instances.isError ? <p role="alert">Unable to load instances. <button onClick={() => void instances.refetch()}>Retry</button></p> : <>
      <p>{total} instances{instances.isFetching ? ' · Updating…' : ''}</p>
      {instances.data.items?.length ? <InstanceTable items={instances.data.items} sort={sort} onSort={field => update(next => next.set('sort', sort === field ? `-${field}` : field))} /> : <p>No instances match this search.</p>}
      <nav className="search-pagination" aria-label="Pagination">
        <button disabled={page === 1} onClick={() => update(next => next.set('page', String(page - 1)), false)}>Previous</button>
        <span>Page {page} of {pages}</span>
        <button disabled={page >= pages} onClick={() => update(next => next.set('page', String(page + 1)), false)}>Next</button>
        <label>Rows per page<select value={pageSize} onChange={event => update(next => next.set('page_size', event.target.value))}>
          {[...new Set([25, 50, 100, 250, 500, pageSize])].sort((a, b) => a - b).map(size => <option key={size}>{size}</option>)}
        </select></label>
      </nav>
    </>}
  </section>;
}
