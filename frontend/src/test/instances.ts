import type { InstanceDetail } from '../api/types';

export function instanceFixture(provider: 'aws' | 'alibaba' = 'aws'): InstanceDetail {
  return {
    provider, account_id: provider === 'aws' ? '111111111111' : '1111111111111111', account_name: 'Demo', account_alias: 'demo-alias', region: 'eu-central-1',
    instance_id: 'i-0123456789abcdef0', name: `${provider}-web`, state: 'running', provider_state: 'Running',
    instance_type: provider === 'aws' ? 't3.small' : 'ecs.t6-c1m2.large', zone: 'eu-central-1a',
    private_ips: ['10.0.0.1', '10.0.0.2'], public_ips: ['192.0.2.1'], tags: { env: 'test', team: 'infra' },
    launch_time: '2026-01-01T00:00:00Z', first_seen: '2026-01-02T00:00:00Z', last_observed: '2026-01-03T00:00:00Z',
    present: true, vpc_id: 'vpc-example', subnet_id: provider === 'aws' ? 'subnet-example' : 'vsw-example',
    key_name: 'example-key', image_id: 'image-example', platform: 'linux',
    details: {
      cpu: 2, memory_mib: provider === 'alibaba' ? 4096 : null,
      image: { id: 'image-example', name: 'Example Linux' }, key_pair: { name: 'example-key' },
      vpc: { id: 'vpc-example', name: 'Example VPC', cidr: '10.0.0.0/16' },
      subnet: { id: provider === 'aws' ? 'subnet-example' : 'vsw-example', name: 'Example subnet', cidr: '10.0.0.0/24' },
      network_interfaces: [{ id: 'eni-example', private_ips: ['10.0.0.1', '10.0.0.2'], public_ip: '192.0.2.1', mac: '02:00:00:00:00:01', security_group_ids: ['sg-example'] }],
      security_groups: [{ id: 'sg-example', name: 'Example group', description: 'Web traffic',
        inbound: [{ protocol: 'tcp', port_range: '443', source: '10.0.0.0/16', description: 'TLS', ...(provider === 'alibaba' ? { policy: 'Drop', priority: 1, source_port_range: '1/65535' } : {}) }],
        outbound: [{ protocol: '-1', port_range: 'all', destination: '0.0.0.0/0', description: 'Egress' }],
      }],
    },
    elastic_ips: [],
    raw: provider === 'aws' ? { InstanceId: 'i-0123456789abcdef0', State: { Name: 'running' } } : { InstanceId: 'i-0123456789abcdef0', Status: 'Running' },
  };
}
