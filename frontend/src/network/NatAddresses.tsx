import { Link } from 'react-router-dom';
import type { NatGatewaySummary } from '../api/types';
import CopyButton from '../CopyButton';
import { elasticIPPath } from './paths';

export default function NatAddresses({ nat, onStatus, details = false }: { nat: NatGatewaySummary; onStatus: (status: string) => void; details?: boolean }) {
  if (!nat.addresses.length) return <>No addresses in inventory</>;
  return <>{nat.addresses.map((address, index) => <div key={index}>
    {address.allocation_id ? <Link to={elasticIPPath({ ...nat, allocation_id: address.allocation_id })}>{address.public_ip || address.allocation_id}</Link> : <span>{address.public_ip || 'No public IP'}</span>}
    {address.public_ip && <CopyButton value={address.public_ip} label={`Copy public IP ${address.public_ip}`} what="Public IP" onStatus={onStatus} />}
    {details && <small>Allocation: {address.allocation_id || '–'} · Private IP: {address.private_ip || '–'} · ENI: {address.network_interface_id || '–'}</small>}
  </div>)}</>;
}
