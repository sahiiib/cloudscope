import { useState } from 'react';
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { useLocation, useSearchParams } from 'react-router-dom';
import { apiFetch } from '../api/client';
import type { AccountSummary, LoadBalancerDetail, LoadBalancerPage, LoadBalancerScans, LoadBalancerSummary } from '../api/types';
import SearchInput from '../search/SearchInput';
import FloatingScroll from '../FloatingScroll';
import { CopyIcon, StateIcon, ViewIcon } from '../icons';
import './load-balancers.css';

function identity(lb: LoadBalancerSummary) {
  return [lb.provider, lb.account_id, lb.region, lb.family, lb.load_balancer_id].map(encodeURIComponent).join('/');
}

function Details({ lb }: { lb: LoadBalancerSummary }) {
  const detail = useQuery({ queryKey: ['load-balancer', identity(lb)], queryFn: async ({ signal }): Promise<LoadBalancerDetail> =>
    (await apiFetch(`/api/load-balancers/${identity(lb)}`, { signal })).json() });
  if (detail.isPending) return <p role="status">Loading load balancer details…</p>;
  if (detail.isError) return <p role="alert">Unable to load details. <button onClick={() => void detail.refetch()}>Retry details</button></p>;
  return <div className="lb-details"><h2>{detail.data.name}</h2>
    {!detail.data.present && <p className="lb-notice">Missing from the last successful scan. Last observed data is retained.</p>}
    <dl><dt>Load balancer ID</dt><dd>{detail.data.load_balancer_id}</dd><dt>Account</dt><dd>{detail.data.account_name} · {detail.data.account_id}</dd>
      <dt>Account alias</dt><dd>{detail.data.account_alias ?? '–'}</dd><dt>VPC</dt><dd>{detail.data.vpc_id ?? 'Not available'}</dd>
      <dt>Availability zones</dt><dd>{detail.data.zones.join(', ') || 'Not available'}</dd>
      <dt>First seen</dt><dd>{new Date(detail.data.first_seen).toLocaleString()}</dd>
      <dt>Last observed</dt><dd>{new Date(detail.data.last_observed).toLocaleString()}</dd></dl>
    <details><summary>Raw provider data</summary><pre>{JSON.stringify(detail.data.raw, null, 2)}</pre></details>
  </div>;
}

export default function LoadBalancers() {
  const location = useLocation();
  const [params, setParams] = useSearchParams();
  const [expanded, setExpanded] = useState<string | null>(null);
  const [copyStatus, setCopyStatus] = useState('');
  async function copy(value: string, what: string) {
    try { await navigator.clipboard.writeText(value); setCopyStatus(`${what} copied.`); }
    catch { setCopyStatus(`Unable to copy. Select and copy the ${what.toLowerCase()}.`); }
  }
  const rawPage = Number(params.get('page') || 1);
  const page = Number.isSafeInteger(rawPage) && rawPage > 0 ? rawPage : 1;
  const query = new URLSearchParams();
  for (const field of ['q', 'provider', 'account_id', 'region', 'kind', 'include_missing']) {
    const value = params.get(field); if (value) query.set(field, value);
  }
  query.set('page', String(page)); query.set('page_size', '50');
  const inventory = useQuery({ queryKey: ['load-balancers', query.toString()], placeholderData: keepPreviousData, refetchInterval: 30000,
    queryFn: async ({ signal }): Promise<LoadBalancerPage> => (await apiFetch(`/api/load-balancers?${query}`, { signal })).json() });
  const scans = useQuery({ queryKey: ['lb-scans'], refetchInterval: 30000, queryFn: async ({ signal }): Promise<LoadBalancerScans> =>
    (await apiFetch('/api/load-balancers/scans', { signal })).json() });
  const accounts = useQuery({ queryKey: ['accounts'], queryFn: async ({ signal }): Promise<AccountSummary[]> =>
    (await apiFetch('/api/accounts', { signal })).json() });
  function update(field: string, value: string) {
    setParams(previous => { const next = new URLSearchParams(previous); if (value) next.set(field, value); else next.delete(field); if (field !== 'page') next.delete('page'); return next; });
    setExpanded(null);
  }
  const failures = scans.data?.items.filter(scan => scan.status === 'error') ?? [];
  return <section className="lb-page"><div className="page-heading"><span className="eyebrow">Network inventory</span>
    <h1>Load balancers</h1><p>AWS and Alibaba load balancers across your accounts and regions.</p></div>
    {scans.data && !scans.data.enabled && <p className="lb-notice">Load balancer collection is disabled. Ask an operator to enable it after configuring read-only permissions. Stored inventory remains available.</p>}
    {scans.data?.enabled && scans.data.items.length === 0 && <p className="lb-notice">No load balancer scans yet. Run a sync to start collecting.</p>}
    {scans.isError && <p role="alert">Unable to load scan status. <button onClick={() => void scans.refetch()}>Retry scan status</button></p>}
    {failures.length > 0 && <p role="alert" className="lb-notice">{failures.length} load balancer scans failed. Previous inventory is retained; check collection status below.</p>}
    <SearchInput label="Search load balancers" placeholder="Name, account, resource ID, address or VPC…" revision={location.key} value={params.get('q') || ''} onChange={value => update('q', value)} />
    <div className="lb-filters">
      <label>Provider<select value={params.get('provider') || ''} onChange={event => update('provider', event.target.value)}>
        <option value="">All providers</option><option value="aws">AWS</option><option value="alibaba">Alibaba</option></select></label>
      <label>Account<select value={params.get('account_id') || ''} onChange={event => update('account_id', event.target.value)}>
        <option value="">All accounts</option>{Array.isArray(accounts.data) && accounts.data.map(account => <option key={`${account.provider}/${account.account_id}`} value={account.account_id}>{account.name} · {account.provider}</option>)}</select></label>
      <label>Region<input value={params.get('region') || ''} onChange={event => update('region', event.target.value)} placeholder="All regions" /></label>
      <label>Type<select value={params.get('kind') || ''} onChange={event => update('kind', event.target.value)}>
        <option value="">All types</option>{['application', 'network', 'gateway', 'classic', 'clb', 'alb', 'nlb'].map(kind => <option key={kind} value={kind}>{kind.toUpperCase()}</option>)}</select></label>
      <label className="lb-toggle"><input type="checkbox" checked={params.get('include_missing') === 'true'} onChange={event => update('include_missing', String(event.target.checked))} />Include missing</label>
      <button className="secondary" onClick={() => { setParams({}); setExpanded(null); }}>Clear filters</button>
    </div>
    {inventory.isPending ? <p role="status">Loading load balancers…</p> : inventory.isError && !inventory.data ?
      <p role="alert">Unable to load load balancers. <button onClick={() => void inventory.refetch()}>Retry inventory</button></p> : <>
      {inventory.isError && <p role="alert">Unable to refresh inventory. Showing previous results. <button onClick={() => void inventory.refetch()}>Retry inventory</button></p>}
      <div className="lb-toolbar"><span>{inventory.data?.total ?? 0} load balancers{inventory.isFetching ? ' · Updating…' : ''}</span>
        <button className="secondary" onClick={() => { void inventory.refetch(); void scans.refetch(); }}>Refresh</button></div>
      <p role="status">{copyStatus}</p>
      {inventory.data?.items.length ? <FloatingScroll className="lb-scroll"><table className="lb-table"><thead><tr>
        {['Name', 'Type', 'State', 'Exposure', 'Address', 'Account', 'Region', 'Observed', 'Details'].map(label => <th key={label} scope="col">{label}</th>)}
      </tr></thead><tbody>{inventory.data.items.map(lb => <tr key={identity(lb)}>
        <td><strong>{lb.name}</strong><small>{lb.provider === 'aws' ? 'AWS' : 'Alibaba Cloud'}{!lb.present && ' · Missing'}</small></td>
        <td><span className="lb-chip">{lb.kind.toUpperCase()}</span></td><td><StateIcon state={lb.state} /></td><td>{lb.scheme}</td>
        <td>{lb.addresses.length ? lb.addresses.map(address => <div key={address}>{address}</div>) : 'Not available'}</td>
        <td>{lb.account_name}<small><code>{lb.account_id}</code> <button className="secondary icon-button" aria-label={`Copy account ID ${lb.account_id}`} title="Copy account ID" onClick={() => void copy(lb.account_id, 'Account ID')}><CopyIcon /></button></small></td><td>{lb.region}</td>
        <td><time dateTime={lb.last_observed}>{new Date(lb.last_observed).toLocaleString()}</time></td>
        <td><button className="secondary icon-button" aria-label={`${expanded === identity(lb) ? 'Hide' : 'View'} ${lb.name}`} title={expanded === identity(lb) ? 'Hide details' : 'View details'} aria-expanded={expanded === identity(lb)} onClick={() => setExpanded(expanded === identity(lb) ? null : identity(lb))}><ViewIcon /></button></td>
      </tr>)}</tbody></table></FloatingScroll> : <p>No load balancers match this search. Check collection status to confirm scans succeeded.</p>}
      {expanded && inventory.data?.items.filter(lb => identity(lb) === expanded).map(lb => <Details key={expanded} lb={lb} />)}
      <nav className="lb-pagination" aria-label="Load balancer pagination"><button disabled={page === 1} onClick={() => update('page', String(page - 1))}>Previous</button>
        <span>Page {page} of {Math.max(1, Math.ceil((inventory.data?.total ?? 0) / 50))}</span>
        <button disabled={page * 50 >= (inventory.data?.total ?? 0)} onClick={() => update('page', String(page + 1))}>Next</button></nav>
    </>}
    {scans.data && <details className="lb-scan-status"><summary>Collection status ({scans.data.items.length} account / region / type scans)</summary>
      <FloatingScroll className="lb-scroll"><table className="lb-table"><thead><tr>{['Provider', 'Account ID', 'Region', 'Family', 'Status', 'Error', 'Last success'].map(label => <th key={label} scope="col">{label}</th>)}</tr></thead>
        <tbody>{scans.data.items.map(scan => <tr key={`${scan.provider}/${scan.account_id}/${scan.region}/${scan.family}`}>
          <td>{scan.provider}</td><td>{scan.account_id}</td><td>{scan.region}</td><td>{scan.family}</td><td>{scan.status}</td><td>{scan.error ?? '–'}</td>
          <td>{scan.last_success ? new Date(scan.last_success).toLocaleString() : 'Never'}</td></tr>)}</tbody></table></FloatingScroll>
    </details>}
  </section>;
}
