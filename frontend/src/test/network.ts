import type { ElasticIPDetail } from '../api/types';
export const eip: ElasticIPDetail = {
  provider: 'aws', account_id: '111111111111', account_name: 'Demo', account_alias: null,
  region: 'us-east-1', allocation_id: 'eipalloc-demo', public_ip: '192.0.2.1', name: 'Demo EIP', status: 'associated',
  associated_type: 'instance', associated_id: 'i-demo', private_ip: '10.0.0.1', network_interface_id: 'eni-demo',
  bandwidth: null, charge_type: null, association: { type: 'instance', id: 'i-demo', link: '/instances/aws/111111111111/us-east-1/i-demo' },
  tags: { env: 'test' }, last_observed: '2026-01-01T00:00:00Z', first_seen: '2026-01-01T00:00:00Z', present: true, raw: { AllocationId: 'eipalloc-demo' },
};
