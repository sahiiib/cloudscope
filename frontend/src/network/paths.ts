import type { ElasticIPSummary } from '../api/types';
export function elasticIPPath(eip: Pick<ElasticIPSummary, 'provider' | 'account_id' | 'region' | 'allocation_id'>) {
  return `/elastic-ips/${[eip.provider, eip.account_id, eip.region, eip.allocation_id].map(encodeURIComponent).join('/')}`;
}
