import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link, useParams } from 'react-router-dom';
import { apiFetch, ApiError } from '../api/client';
import type { ElasticIPDetail } from '../api/types';
import CopyButton from '../CopyButton';
import Association from './Association';
import '../load-balancers/load-balancers.css';

export default function ElasticIPDetails() {
  const { provider = '', account = '', region = '', id = '' } = useParams();
  const valid = ['aws', 'alibaba'].includes(provider) && !!account && !!region && !!id;
  const path = [provider, account, region, id].map(encodeURIComponent).join('/');
  const [copyStatus, setCopyStatus] = useState('');
  const detail = useQuery({ queryKey: ['elastic-ip', path], enabled: valid, retry: false,
    queryFn: async ({ signal }): Promise<ElasticIPDetail> => (await apiFetch(`/api/elastic-ips/${path}`, { signal })).json() });
  const eip = detail.data;
  return <section className="lb-page"><Link to="/elastic-ips">Back to Elastic IPs</Link><h1>Elastic IP details</h1>
    {!valid || (detail.error instanceof ApiError && detail.error.status === 404) ? <p role="alert">Elastic IP not found.</p>
      : detail.isPending ? <p role="status">Loading Elastic IP details…</p>
      : !eip ? <p role="alert">Unable to load details. <button onClick={() => void detail.refetch()}>Retry details</button></p>
      : <div className="lb-details"><h2>{eip.name || eip.allocation_id}</h2>
        {detail.isError && <p role="alert">Unable to refresh details. <button onClick={() => void detail.refetch()}>Retry details</button></p>}
        {!eip.present && <p className="lb-notice">Missing from the last successful scan. Last observed data is retained.</p>}
        <p role="status">{copyStatus}</p>
        <dl>{Object.entries({ Provider: eip.provider, 'Allocation ID': eip.allocation_id, 'Public IP': eip.public_ip, Name: eip.name, Status: eip.status, 'Private IP': eip.private_ip, 'Network interface': eip.network_interface_id, Bandwidth: eip.bandwidth, 'Charge type': eip.charge_type, Account: eip.account_name, 'Account ID': eip.account_id, 'Account alias': eip.account_alias, Region: eip.region, 'First seen': eip.first_seen, Observed: eip.last_observed }).map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value || '–'}{value && ['Allocation ID', 'Public IP', 'Private IP', 'Network interface', 'Account ID'].includes(label) && <CopyButton value={value} label={`Copy ${label}`} what={label} onStatus={setCopyStatus} />}</dd></div>)}
          <dt>Associated with</dt><dd><Association association={eip.association} onStatus={setCopyStatus} /></dd></dl>
        <h3>Tags</h3><pre>{JSON.stringify(eip.tags, null, 2)}</pre>
        <details><summary>Raw provider data</summary><pre>{JSON.stringify(eip.raw, null, 2)}</pre></details>
      </div>}
  </section>;
}
