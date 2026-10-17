import type { NatGatewayDetail } from '../api/types';
export const nat: NatGatewayDetail = {
  provider: 'aws', account_id: '111111111111', account_name: 'Demo', account_alias: 'demo-alias', region: 'us-east-1',
  nat_gateway_id: 'nat-demo', name: 'Demo NAT', state: 'available', connectivity_type: 'public', nat_type: null,
  network_type: null, spec: null, vpc_id: 'vpc-demo', subnet_id: 'subnet-demo', private_ip: null,
  addresses: [{ allocation_id: 'eipalloc-demo', public_ip: '192.0.2.1', private_ip: '10.0.0.1', network_interface_id: 'eni-demo' }],
  tags: { env: 'test' }, first_seen: '2026-01-01T00:00:00Z', last_observed: '2026-01-01T00:00:00Z', present: true, raw: { NatGatewayId: 'nat-demo' },
};
