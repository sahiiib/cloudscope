import { fireEvent, screen, waitFor } from '@testing-library/react';
import { expect, test, vi } from 'vitest';
import { ApiError } from '../api/client';
import { fetchApi, response, setup, user } from '../test/auth';
import type { LoadBalancerSummary } from '../api/types';

const lb: LoadBalancerSummary = { provider: 'aws', account_id: '111111111111', account_name: 'Demo', account_alias: 'demo-alias',
  region: 'us-east-1', family: 'elbv2', load_balancer_id: 'arn:aws:elasticloadbalancing:us-east-1:111111111111:loadbalancer/app/demo/1',
  name: 'web-lb', kind: 'application', state: 'active', scheme: 'internet-facing', addresses: ['demo.example.com'], vpc_id: 'vpc-test',
  zones: ['us-east-1a'], tags: {}, last_observed: '2026-01-01T00:00:00Z', present: true };
function mock(options: { enabled?: boolean; error?: boolean; empty?: boolean } = {}) {
  fetchApi.mockImplementation(async path => {
    if (path === '/api/auth/me') return response(user);
    if (path === '/api/accounts') return response([]);
    if (path === '/api/load-balancers/scans') return response({ enabled: options.enabled ?? true, items: options.error ?
      [{ provider: 'aws', account_id: lb.account_id, region: lb.region, family: 'elbv2', status: 'error', error: 'AccessDenied', last_attempt: lb.last_observed, last_success: null }] : [] });
    if (path.startsWith('/api/load-balancers?')) return response({ items: options.empty ? [] : [lb], total: options.empty ? 0 : 51, page: 1, page_size: 50 });
    return response({ ...lb, raw: { Type: 'application' }, first_seen: lb.last_observed });
  });
}
test('shows inventory, details and encoded ARN identity', async () => {
  mock(); setup('/load-balancers');
  expect(await screen.findByText('demo.example.com')).toBeInTheDocument();
  expect(screen.getByRole('searchbox', { name: 'Search load balancers' })).toHaveAttribute('placeholder', 'Name, account, resource ID, address or VPC…');
  expect(screen.getByRole('img', { name: 'active' })).toHaveClass('state-running');
  fireEvent.click(screen.getByRole('link', { name: 'View web-lb' }));
  expect(await screen.findByRole('heading', { name: 'Load balancer details' })).toBeInTheDocument();
  expect(await screen.findByText('vpc-test')).toBeInTheDocument();
  expect(screen.getByText('demo-alias')).toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'Back to load balancers' })).toHaveAttribute('href', '/load-balancers');
  expect(fetchApi).toHaveBeenCalledWith(`/api/load-balancers/aws/111111111111/us-east-1/elbv2/${encodeURIComponent(lb.load_balancer_id)}`, expect.anything());
});
test('filters and pagination are restored from the URL and filters reset pagination', async () => {
  mock(); setup('/load-balancers?provider=alibaba&kind=alb&page=2&include_missing=true');
  await screen.findByText('demo.example.com');
  expect(screen.getByLabelText('Provider')).toHaveValue('alibaba');
  expect(screen.getByLabelText('Include missing')).toBeChecked();
  fireEvent.change(screen.getByLabelText('Type'), { target: { value: 'nlb' } });
  await waitFor(() => expect(fetchApi).toHaveBeenCalledWith(expect.stringContaining('kind=nlb&include_missing=true&page=1'), expect.anything()));
});
test('disabled and failed scans are explicit and never presented as an empty successful scan', async () => {
  mock({ enabled: false, error: true, empty: true }); setup('/load-balancers');
  expect(await screen.findByText(/collection is disabled/)).toBeInTheDocument();
  expect(screen.getByRole('alert')).toHaveTextContent('Previous inventory is retained');
  expect(screen.getByText('AccessDenied')).toBeInTheDocument();
});
test('failed inventory requests offer retry', async () => {
  mock(); const original = fetchApi.getMockImplementation()!;
  fetchApi.mockImplementation(path => path.startsWith('/api/load-balancers?') ? Promise.reject(new ApiError(503)) : original(path));
  setup('/load-balancers');
  expect(await screen.findByRole('alert')).toHaveTextContent('Unable to load load balancers');
  mock(); fireEvent.click(screen.getByRole('button', { name: 'Retry inventory' }));
  expect(await screen.findByText('demo.example.com')).toBeInTheDocument();
});

test('copies a load balancer address from the table', async () => {
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
  mock(); setup('/load-balancers');
  fireEvent.click(await screen.findByRole('button', { name: 'Copy address demo.example.com' }));
  await waitFor(() => expect(writeText).toHaveBeenCalledWith('demo.example.com'));
  expect(await screen.findByText('Address copied.')).toBeInTheDocument();
});
test('details page reports an unknown load balancer', async () => {
  mock(); const original = fetchApi.getMockImplementation()!;
  fetchApi.mockImplementation(path => path.startsWith('/api/load-balancers/aws/') ? Promise.reject(new ApiError(404)) : original(path));
  setup('/load-balancers/aws/111111111111/us-east-1/elbv2/missing');
  expect(await screen.findByRole('alert')).toHaveTextContent('Load balancer not found.');
});
