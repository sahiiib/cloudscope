import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link, useParams } from 'react-router-dom';
import { apiFetch, ApiError } from '../api/client';
import type { NatGatewayDetail } from '../api/types';
import CopyButton from '../CopyButton';
import NatAddresses from './NatAddresses';
import '../load-balancers/load-balancers.css';

export default function NatGatewayDetails() {
  const { provider = '', account = '', region = '', id = '' } = useParams();
  const valid = ['aws', 'alibaba'].includes(provider) && !!account && !!region && !!id;
  const path = [provider, account, region, id].map(encodeURIComponent).join('/');
  const [copyStatus, setCopyStatus] = useState('');
  const detail = useQuery({ queryKey: ['nat-gateway', path], enabled: valid, retry: false,
    queryFn: async ({ signal }): Promise<NatGatewayDetail> => (await apiFetch(`/api/nat-gateways/${path}`, { signal })).json() });
  const nat = detail.data;
  return <section className="lb-page"><Link to="/nat-gateways">Back to NAT gateways</Link><h1>NAT gateway details</h1>
    {!valid || (detail.error instanceof ApiError && detail.error.status === 404) ? <p role="alert">NAT gateway not found.</p>
      : detail.isPending ? <p role="status">Loading NAT gateway details…</p>
      : !nat ? <p role="alert">Unable to load details. <button onClick={() => void detail.refetch()}>Retry details</button></p>
      : <div className="lb-details"><h2>{nat.name || nat.nat_gateway_id}</h2>
        {detail.isError && <p role="alert">Unable to refresh details. <button onClick={() => void detail.refetch()}>Retry details</button></p>}
        {!nat.present && <p className="lb-notice">Missing from the last successful scan. Last observed data is retained.</p>}
        <p role="status">{copyStatus}</p>
        <dl>{Object.entries({ Provider: nat.provider, 'NAT gateway ID': nat.nat_gateway_id, Name: nat.name, State: nat.state, 'Connectivity type': nat.connectivity_type, 'NAT type': nat.nat_type, 'Network type': nat.network_type, Spec: nat.spec, VPC: nat.vpc_id, 'Subnet / vSwitch': nat.subnet_id, 'Private IP': nat.private_ip, Account: nat.account_name, 'Account ID': nat.account_id, 'Account alias': nat.account_alias, Region: nat.region, 'First seen': nat.first_seen, Observed: nat.last_observed }).map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value || '–'}{value && ['NAT gateway ID', 'Private IP', 'Account ID', 'VPC', 'Subnet / vSwitch'].includes(label) && <CopyButton value={value} label={`Copy ${label}`} what={label} onStatus={setCopyStatus} />}</dd></div>)}</dl>
        <h3>Addresses</h3><NatAddresses nat={nat} onStatus={setCopyStatus} details />
        <h3>Tags</h3><pre>{JSON.stringify(nat.tags, null, 2)}</pre>
        <details><summary>Raw provider data</summary><pre>{JSON.stringify(nat.raw, null, 2)}</pre></details>
      </div>}
  </section>;
}
