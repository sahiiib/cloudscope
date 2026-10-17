import { fireEvent, screen, waitFor } from '@testing-library/react';
import { expect, test, vi } from 'vitest';
import { ApiError } from '../api/client';
import { fetchApi, response, setup, user } from '../test/auth';
import { eip } from '../test/network';
import { instanceFixture } from '../test/instances';
function mock(link: string | null = eip.association!.link, options: { disabled?: boolean; failed?: boolean; empty?: boolean } = {}) {
  fetchApi.mockImplementation(async path => {
    if (path === '/api/auth/me') return response(user);
    if (path === '/api/accounts') return response([]);
    if (path === '/api/network/scans') return response({ enabled: !options.disabled, items: options.failed ? [{ provider: 'aws', account_id: eip.account_id, region: eip.region, resource_type: 'elastic_ip', status: 'error', error: 'AccessDenied', last_success: null }] : [] });
    if (path.startsWith('/api/elastic-ips?')) return response({ items: options.empty ? [] : [{ ...eip, association: { ...eip.association, link } }], total: options.empty ? 0 : 51, page: 1, page_size: 50 });
    if (path.startsWith('/api/load-balancers/')) return response({ name: 'Demo LB', load_balancer_id: 'lb-demo', kind: 'network', state: 'active', scheme: 'internet-facing', addresses: [], zones: [], account_name: 'Demo', account_id: eip.account_id, region: eip.region, first_seen: eip.first_seen, last_observed: eip.last_observed, present: true, raw: {} });
    if (path.startsWith('/api/instances/')) return response(instanceFixture());
    return response(eip);
  });
}
test.each(['click', 'Enter'])('row %s opens the associated instance', async action => {
  mock(); setup('/elastic-ips');
  const row = await screen.findByRole('row', { name: 'Open 192.0.2.1' });
  expect(screen.getByRole('link', { name: 'instance · i-demo' })).toHaveAttribute('href', eip.association!.link);
  if (action === 'click') fireEvent.click(row); else fireEvent.keyDown(row, { key: action });
  expect(await screen.findByRole('heading', { name: 'Instance details' })).toBeInTheDocument();
});
test('row with no inventory link opens EIP details, View always opens EIP details', async () => {
  mock(null); setup('/elastic-ips');
  fireEvent.click(await screen.findByRole('row', { name: 'Open 192.0.2.1' }));
  expect(await screen.findByRole('heading', { name: 'Elastic IP details' })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('link', { name: 'Back to Elastic IPs' }));
  mock();
  fireEvent.click(await screen.findByRole('link', { name: 'View 192.0.2.1' }));
  expect(await screen.findByRole('heading', { name: 'Elastic IP details' })).toBeInTheDocument();
});
test('copy buttons do not navigate and association links follow their target', async () => {
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
  mock(); setup('/elastic-ips');
  fireEvent.click(await screen.findByRole('button', { name: 'Copy public IP 192.0.2.1' }));
  await waitFor(() => expect(writeText).toHaveBeenCalledWith('192.0.2.1'));
  expect(screen.getByRole('heading', { name: 'Elastic IPs' })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('link', { name: 'instance · i-demo' }));
  expect(await screen.findByRole('heading', { name: 'Instance details' })).toBeInTheDocument();
});
test('URL filters, paging and include missing survive navigation', async () => {
  mock(); setup('/elastic-ips?provider=aws&status=associated&associated_type=instance&page=2&include_missing=true');
  await screen.findByRole('row', { name: 'Open 192.0.2.1' });
  expect(screen.getByLabelText('Status')).toHaveValue('associated');
  expect(screen.getByLabelText('Associated type')).toHaveValue('instance');
  expect(screen.getByLabelText('Include missing')).toBeChecked();
  fireEvent.change(screen.getByLabelText('Status'), { target: { value: 'available' } });
  await waitFor(() => expect(fetchApi).toHaveBeenCalledWith(expect.stringContaining('status=available&associated_type=instance&include_missing=true&page=1'), expect.anything()));
});
test('disabled, failed and never-run scans are explicit', async () => {
  mock(null, { disabled: true, failed: true, empty: true }); setup('/elastic-ips');
  expect(await screen.findByText(/collection is disabled/)).toBeInTheDocument();
  expect(screen.getByRole('alert')).toHaveTextContent('Previous inventory is retained');
  expect(screen.getByText('AccessDenied')).toBeInTheDocument();
});
test('never-run and inventory failure with retry', async () => {
  mock(); const original = fetchApi.getMockImplementation()!;
  fetchApi.mockImplementation(path => path.startsWith('/api/elastic-ips?') ? Promise.reject(new ApiError(503)) : original(path));
  setup('/elastic-ips');
  expect(await screen.findByText(/No Elastic IP scans yet/)).toBeInTheDocument();
  expect(await screen.findByRole('alert')).toHaveTextContent('Unable to load Elastic IPs');
  mock(); fireEvent.click(screen.getByRole('button', { name: 'Retry inventory' }));
  expect(await screen.findByRole('row', { name: 'Open 192.0.2.1' })).toBeInTheDocument();
});

test('row opens an associated load balancer, while View still opens EIP details', async () => {
  mock('/load-balancers/aws/111111111111/us-east-1/elbv2/lb-demo'); setup('/elastic-ips');
  fireEvent.click(await screen.findByRole('row', { name: 'Open 192.0.2.1' }));
  expect(await screen.findByRole('heading', { name: 'Load balancer details' })).toBeInTheDocument();
});
