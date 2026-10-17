import { useState } from 'react';
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { Link, useLocation, useSearchParams, useNavigate } from 'react-router-dom';
import { apiFetch } from '../api/client';
import type { AccountSummary, NatGatewayPage, NetworkScans } from '../api/types';
import SearchInput from '../search/SearchInput';
import FloatingScroll from '../FloatingScroll';
import CopyButton from '../CopyButton';
import { ViewIcon } from '../icons';
import '../load-balancers/load-balancers.css';
import NatAddresses from './NatAddresses';
import { natGatewayPath } from './paths';

export default function NatGateways() {
  const navigate = useNavigate();
  const location = useLocation();
  const [params, setParams] = useSearchParams();
  const [copyStatus, setCopyStatus] = useState('');
  const rawPage = Number(params.get('page') || 1);
  const page = Number.isSafeInteger(rawPage) && rawPage > 0 ? rawPage : 1;
  const query = new URLSearchParams();
  for (const field of ['q', 'provider', 'account_id', 'region', 'state', 'include_missing']) {
    const value = params.get(field); if (value) query.set(field, value);
  }
  query.set('page', String(page)); query.set('page_size', '50');
  const inventory = useQuery({ queryKey: ['nat-gateways', query.toString()], placeholderData: keepPreviousData, refetchInterval: 30000,
    queryFn: async ({ signal }): Promise<NatGatewayPage> => (await apiFetch(`/api/nat-gateways?${query}`, { signal })).json() });
  const scans = useQuery({ queryKey: ['network-scans'], refetchInterval: 30000, queryFn: async ({ signal }): Promise<NetworkScans> =>
    (await apiFetch('/api/network/scans', { signal })).json() });
  const accounts = useQuery({ queryKey: ['accounts'], queryFn: async ({ signal }): Promise<AccountSummary[]> =>
    (await apiFetch('/api/accounts', { signal })).json() });
  function update(field: string, value: string) {
    setParams(previous => { const next = new URLSearchParams(previous); if (value) next.set(field, value); else next.delete(field); if (field !== 'page') next.delete('page'); return next; });
  }
  const scanRows = scans.data?.items.filter(scan => scan.resource_type === 'nat_gateway') ?? [];
  const failures = scans.data?.items.filter(scan => scan.resource_type === 'nat_gateway' && scan.status === 'error') ?? [];
  return <section className="lb-page"><div className="page-heading"><span className="eyebrow">Network inventory</span>
    <h1>NAT gateways</h1><p>AWS and Alibaba NAT gateways across your accounts and regions.</p></div>
    {scans.data && !scans.data.enabled && <p className="lb-notice">NAT gateway collection is disabled. Ask an operator to enable it after configuring read-only permissions. Stored inventory remains available.</p>}
    {scans.data?.enabled && scanRows.length === 0 && <p className="lb-notice">No NAT gateway scans yet. Run a sync to start collecting.</p>}
    {scans.isError && <p role="alert">Unable to load scan status. <button onClick={() => void scans.refetch()}>Retry scan status</button></p>}
    {failures.length > 0 && <p role="alert" className="lb-notice">{failures.length} NAT gateway scans failed. Previous inventory is retained; check collection status below.</p>}
    <SearchInput label="Search NAT gateways" placeholder="Name, ID, IP, VPC or account…" revision={location.key} value={params.get('q') || ''} onChange={value => update('q', value)} />
    <div className="lb-filters">
      <label>Provider<select value={params.get('provider') || ''} onChange={event => update('provider', event.target.value)}>
        <option value="">All providers</option><option value="aws">AWS</option><option value="alibaba">Alibaba</option></select></label>
      <label>Account<select value={params.get('account_id') || ''} onChange={event => update('account_id', event.target.value)}>
        <option value="">All accounts</option>{Array.isArray(accounts.data) && accounts.data.map(account => <option key={`${account.provider}/${account.account_id}`} value={account.account_id}>{account.name} · {account.provider}</option>)}</select></label>
      <label>Region<input value={params.get('region') || ''} onChange={event => update('region', event.target.value)} placeholder="All regions" /></label>
      <label>State<input value={params.get('state') || ''} onChange={event => update('state', event.target.value)} placeholder="All states" /></label>
      <label className="lb-toggle"><input type="checkbox" checked={params.get('include_missing') === 'true'} onChange={event => update('include_missing', String(event.target.checked))} />Include missing</label>
      <button className="secondary" onClick={() => setParams({})}>Clear filters</button>
    </div>
    {inventory.isPending ? <p role="status">Loading NAT gateways…</p> : inventory.isError && !inventory.data ?
      <p role="alert">Unable to load NAT gateways. <button onClick={() => void inventory.refetch()}>Retry inventory</button></p> : <>
      {inventory.isError && <p role="alert">Unable to refresh inventory. Showing previous results. <button onClick={() => void inventory.refetch()}>Retry inventory</button></p>}
      <div className="lb-toolbar"><span>{inventory.data?.total ?? 0} NAT gateways{inventory.isFetching ? ' · Updating…' : ''}</span>
        <button className="secondary" onClick={() => { void inventory.refetch(); void scans.refetch(); }}>Refresh</button></div>
      <p role="status">{copyStatus}</p>
      {inventory.data?.items.length ? <FloatingScroll className="lb-scroll"><table className="lb-table"><thead><tr>
        {['Name', 'ID', 'State', 'Type', 'Public IPs', 'Private IPs', 'VPC', 'Account', 'Region', 'Observed', 'View'].map(label => <th key={label} scope="col">{label}</th>)}
      </tr></thead><tbody>{inventory.data.items.map(nat => <tr key={natGatewayPath(nat)} tabIndex={0} aria-label={`Open ${nat.nat_gateway_id}`}
        onClick={event => { if (!(event.target as HTMLElement).closest('a,button,input,select')) navigate(natGatewayPath(nat)); }}
        onKeyDown={event => { if (event.key === 'Enter' && event.target === event.currentTarget) { event.preventDefault(); navigate(natGatewayPath(nat)); } }}>
        <td>{nat.name || '–'}{!nat.present && <small>Missing</small>}</td>
        <td><code>{nat.nat_gateway_id}</code><CopyButton value={nat.nat_gateway_id} label={`Copy NAT gateway ID ${nat.nat_gateway_id}`} what="NAT gateway ID" onStatus={setCopyStatus} /></td>
        <td>{nat.state}</td><td>{[nat.connectivity_type, nat.nat_type, nat.network_type].filter(Boolean).join(' · ') || '–'}</td>
        <td><NatAddresses nat={nat} onStatus={setCopyStatus} /></td>
        <td>{[...new Set([nat.private_ip, ...nat.addresses.map(address => address.private_ip)].filter(Boolean))].join(', ') || '–'}</td>
        <td>{nat.vpc_id || '–'}</td>
        <td>{nat.account_name}<small><code>{nat.account_id}</code><CopyButton value={nat.account_id} label={`Copy account ID ${nat.account_id}`} what="Account ID" onStatus={setCopyStatus} /></small></td>
        <td>{nat.region}</td><td><time dateTime={nat.last_observed}>{new Date(nat.last_observed).toLocaleString()}</time></td>
        <td><Link to={natGatewayPath(nat)} className="secondary icon-button" aria-label={`View ${nat.nat_gateway_id}`} title="View NAT gateway details"><ViewIcon /></Link></td>
      </tr>)}</tbody></table></FloatingScroll> : <p>No NAT gateways match this search. Check collection status to confirm scans succeeded.</p>}
      <nav className="lb-pagination" aria-label="NAT gateway pagination"><button disabled={page === 1} onClick={() => update('page', String(page - 1))}>Previous</button>
        <span>Page {page} of {Math.max(1, Math.ceil((inventory.data?.total ?? 0) / 50))}</span>
        <button disabled={page * 50 >= (inventory.data?.total ?? 0)} onClick={() => update('page', String(page + 1))}>Next</button></nav>
    </>}
    {scans.data && <details className="lb-scan-status"><summary>Collection status ({scanRows.length} account / region / type scans)</summary>
      <FloatingScroll className="lb-scroll"><table className="lb-table"><thead><tr>{['Provider', 'Account ID', 'Region', 'Resource type', 'Status', 'Error', 'Last success'].map(label => <th key={label} scope="col">{label}</th>)}</tr></thead>
        <tbody>{scanRows.map(scan => <tr key={`${scan.provider}/${scan.account_id}/${scan.region}/${scan.resource_type}`}>
          <td>{scan.provider}</td><td>{scan.account_id}</td><td>{scan.region}</td><td>{scan.resource_type}</td><td>{scan.status}</td><td>{scan.error ?? '–'}</td>
          <td>{scan.last_success ? new Date(scan.last_success).toLocaleString() : 'Never'}</td></tr>)}</tbody></table></FloatingScroll>
    </details>}
  </section>;
}
