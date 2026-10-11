import type { InstanceDetail } from '../api/types';

export default function Network({ instance: i }: { instance: InstanceDetail }) {
  const segments = [
    { label: 'VPC', data: i.details?.vpc, id: i.vpc_id },
    { label: i.provider === 'alibaba' ? 'vSwitch' : 'Subnet', data: i.details?.subnet, id: i.subnet_id },
  ];
  return <section aria-labelledby="instance-network"><h2 id="instance-network">Network</h2>
    {segments.map(({ label, data, id }) => <div key={label}><h3>{label}</h3>
      {!data && !id ? <p>Not available</p> : <dl className="instance-fields">
        <div><dt>ID</dt><dd>{data?.id || id || 'Not available'}</dd></div>
        <div><dt>Name</dt><dd>{data?.name || 'Not available'}</dd></div>
        <div><dt>CIDR</dt><dd>{data?.cidr || 'Not available'}</dd></div>
      </dl>}
    </div>)}
    <h3>Network interfaces</h3>
    {!i.details?.network_interfaces?.length ? <p>Not available</p> : <div className="detail-scroll"><table><caption className="sr-only">Network interfaces</caption>
      <thead><tr><th>ID</th><th>Private IPs</th><th>Public IP</th><th>MAC</th><th>Security groups</th></tr></thead>
      <tbody>{i.details.network_interfaces.map(eni => <tr key={eni.id}><td>{eni.id}</td><td>{eni.private_ips?.join(', ') || 'Not available'}</td>
        <td>{eni.public_ip || 'Not available'}</td><td>{eni.mac || 'Not available'}</td><td>{eni.security_group_ids?.join(', ') || 'Not available'}</td></tr>)}</tbody>
    </table></div>}
  </section>;
}
