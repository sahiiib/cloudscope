import type { ElasticIPSummary, NatGatewaySummary } from '../api/types';
export function elasticIPPath(eip: Pick<ElasticIPSummary, 'provider' | 'account_id' | 'region' | 'allocation_id'>) {
  return `/elastic-ips/${[eip.provider, eip.account_id, eip.region, eip.allocation_id].map(encodeURIComponent).join('/')}`;
}

export function natGatewayPath(nat: Pick<NatGatewaySummary, 'provider' | 'account_id' | 'region' | 'nat_gateway_id'>) {
  return `/nat-gateways/${[nat.provider, nat.account_id, nat.region, nat.nat_gateway_id].map(encodeURIComponent).join('/')}`;
}
