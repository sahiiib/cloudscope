import type { InstanceDetail } from '../api/types';

export default function Summary({ instance: i }: { instance: InstanceDetail }) {
  const fields = {
    Name: i.name, 'Instance ID': i.instance_id, State: i.state, 'Provider state': i.provider_state,
    Type: i.instance_type, Provider: i.provider === 'aws' ? 'AWS' : 'Alibaba',
    Account: `${i.account_name} · ${i.account_id}`, Region: i.region, Zone: i.zone,
    Presence: i.present ? 'Present' : 'Missing', Platform: i.platform,
    Image: i.image_id ?? i.details?.image?.id, 'Image name': i.details?.image?.name,
    'Key pair': i.key_name ?? i.details?.key_pair?.name, 'CPU (vCPU)': i.details?.cpu,
    'Memory (MiB)': i.details?.memory_mib, 'IAM role': i.details?.iam_role,
    Monitoring: i.details?.monitoring, 'Private IPs': i.private_ips.join(', '), 'Public IPs': i.public_ips.join(', '),
  };
  const dates = { 'Launch time': i.launch_time, 'First seen': i.first_seen, 'Last observed': i.last_observed };
  return <section aria-labelledby="instance-summary"><h2 id="instance-summary">Summary</h2>
    <dl className="instance-fields">{Object.entries(fields).map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value === '' || value == null ? 'Not available' : value}</dd></div>)}
      {Object.entries(dates).map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value ? <time dateTime={value}>{value}</time> : 'Not available'}</dd></div>)}
    </dl>
  </section>;
}
