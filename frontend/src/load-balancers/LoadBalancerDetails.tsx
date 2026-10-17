import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link, useParams } from 'react-router-dom';
import { apiFetch, ApiError } from '../api/client';
import type { LoadBalancerDetail } from '../api/types';
import CopyButton from '../CopyButton';
import { StateIcon } from '../icons';
import './load-balancers.css';

export default function LoadBalancerDetails() {
  const { provider = '', account = '', region = '', family = '', id = '' } = useParams();
  const valid = ['aws', 'alibaba'].includes(provider) && !!account && !!region && !!family && !!id;
  const path = [provider, account, region, family, id].map(encodeURIComponent).join('/');
  const [copyStatus, setCopyStatus] = useState('');
  const detail = useQuery({ queryKey: ['load-balancer', path], enabled: valid, retry: false,
    queryFn: async ({ signal }): Promise<LoadBalancerDetail> => (await apiFetch(`/api/load-balancers/${path}`, { signal })).json() });
  return <section className="lb-page"><Link to="/load-balancers">Back to load balancers</Link><h1>Load balancer details</h1>
    {!valid || (detail.error instanceof ApiError && detail.error.status === 404) ? <p role="alert">Load balancer not found.</p>
      : detail.isPending ? <p role="status">Loading load balancer details…</p>
      : !detail.data ? <p role="alert">Unable to load details. <button onClick={() => void detail.refetch()}>Retry details</button></p>
      : <div className="lb-details"><h2>{detail.data.name}</h2>
        {detail.isError && <p role="alert">Unable to refresh details. <button onClick={() => void detail.refetch()}>Retry details</button></p>}
        {!detail.data.present && <p className="lb-notice">Missing from the last successful scan. Last observed data is retained.</p>}
        <p role="status">{copyStatus}</p>
        <dl><dt>Load balancer ID</dt><dd><code>{detail.data.load_balancer_id}</code> <CopyButton value={detail.data.load_balancer_id} label="Copy load balancer ID" what="Load balancer ID" onStatus={setCopyStatus} /></dd>
          <dt>Type</dt><dd>{detail.data.kind.toUpperCase()} · {detail.data.scheme}</dd>
          <dt>State</dt><dd><StateIcon state={detail.data.state} /> {detail.data.state}</dd>
          <dt>Address</dt><dd>{detail.data.addresses.length ? detail.data.addresses.map(address => <div className="copy-wrap" key={address}><code>{address}</code><CopyButton value={address} label={`Copy address ${address}`} what="Address" onStatus={setCopyStatus} /></div>) : 'Not available'}</dd>
          <dt>Account</dt><dd>{detail.data.account_name} · <code>{detail.data.account_id}</code> <CopyButton value={detail.data.account_id} label={`Copy account ID ${detail.data.account_id}`} what="Account ID" onStatus={setCopyStatus} /></dd>
          <dt>Account alias</dt><dd>{detail.data.account_alias ?? '–'}</dd><dt>Region</dt><dd>{detail.data.region}</dd>
          <dt>VPC</dt><dd>{detail.data.vpc_id ?? 'Not available'}</dd>
          <dt>Availability zones</dt><dd>{detail.data.zones.join(', ') || 'Not available'}</dd>
          <dt>First seen</dt><dd>{new Date(detail.data.first_seen).toLocaleString()}</dd>
          <dt>Last observed</dt><dd>{new Date(detail.data.last_observed).toLocaleString()}</dd></dl>
        <details><summary>Raw provider data</summary><pre>{JSON.stringify(detail.data.raw, null, 2)}</pre></details>
      </div>}
  </section>;
}
