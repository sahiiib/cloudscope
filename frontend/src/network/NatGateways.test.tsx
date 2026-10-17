import { fireEvent, screen, waitFor } from '@testing-library/react';
import { expect, test, vi } from 'vitest';
import { ApiError } from '../api/client';
import { fetchApi, response, setup, user } from '../test/auth';
import { nat } from '../test/nat';
import { eip } from '../test/network';
function mock(options: { disabled?: boolean; failed?: boolean; empty?: boolean } = {}) {
  fetchApi.mockImplementation(async path => {
    if (path === '/api/auth/me') return response(user);
    if (path === '/api/accounts') return response([]);
    if (path === '/api/network/scans') return response({ enabled: !options.disabled, items: options.failed ? [{ provider: 'aws', account_id: nat.account_id, region: nat.region, resource_type: 'nat_gateway', status: 'error', error: 'AccessDenied', last_success: null }] : [] });
    if (path.startsWith('/api/nat-gateways?')) return response({ items: options.empty ? [] : [nat], total: options.empty ? 0 : 51, page: 1, page_size: 50 });
    if (path.startsWith('/api/elastic-ips/')) return response(eip);
    return response(nat);
  });
}
test.each(['click', 'Enter', 'View'])('%s opens NAT details', async action => {
  mock(); setup('/nat-gateways');
  const row = await screen.findByRole('row', { name: 'Open nat-demo' });
  if (action === 'click') fireEvent.click(row);
  else if (action === 'Enter') fireEvent.keyDown(row, { key: action });
  else fireEvent.click(screen.getByRole('link', { name: 'View nat-demo' }));
  expect(await screen.findByRole('heading', { name: 'NAT gateway details' })).toBeInTheDocument();
  expect(await screen.findByText('subnet-demo')).toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'Back to NAT gateways' })).toHaveAttribute('href', '/nat-gateways');
});
test('copy controls stay on the page and EIP links bypass row navigation', async () => {
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
  mock(); setup('/nat-gateways');
  fireEvent.click(await screen.findByRole('button', { name: 'Copy NAT gateway ID nat-demo' }));
  await waitFor(() => expect(writeText).toHaveBeenCalledWith('nat-demo'));
  expect(screen.getByRole('heading', { name: 'NAT gateways' })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('link', { name: '192.0.2.1' }));
  expect(await screen.findByRole('heading', { name: 'Elastic IP details' })).toBeInTheDocument();
});
test('URL filters and pagination are restored and reset on filter change', async () => {
  mock(); setup('/nat-gateways?provider=aws&state=deleted&page=2&include_missing=true');
  await screen.findByRole('row', { name: 'Open nat-demo' });
  expect(screen.getByLabelText('State')).toHaveValue('deleted');
  expect(screen.getByLabelText('Include missing')).toBeChecked();
  fireEvent.change(screen.getByLabelText('State'), { target: { value: 'available' } });
  await waitFor(() => expect(fetchApi).toHaveBeenCalledWith(expect.stringContaining('state=available&include_missing=true&page=1'), expect.anything()));
  fireEvent.click(screen.getByRole('button', { name: 'Next' }));
  await waitFor(() => expect(fetchApi).toHaveBeenCalledWith(expect.stringContaining('page=2'), expect.anything()));
});
test('disabled and failed scans preserve explicit coverage warnings', async () => {
  mock({ disabled: true, failed: true, empty: true }); setup('/nat-gateways');
  expect(await screen.findByText(/collection is disabled/)).toBeInTheDocument();
  expect(screen.getByRole('alert')).toHaveTextContent('Previous inventory is retained');
  expect(screen.getByText('AccessDenied')).toBeInTheDocument();
});
test('never-run scans and failed list requests with retry', async () => {
  mock(); const original = fetchApi.getMockImplementation()!;
  fetchApi.mockImplementation(path => path.startsWith('/api/nat-gateways?') ? Promise.reject(new ApiError(503)) : original(path));
  setup('/nat-gateways');
  expect(await screen.findByText(/No NAT gateway scans yet/)).toBeInTheDocument();
  expect(await screen.findByRole('alert')).toHaveTextContent('Unable to load NAT gateways');
  mock(); fireEvent.click(screen.getByRole('button', { name: 'Retry inventory' }));
  expect(await screen.findByRole('row', { name: 'Open nat-demo' })).toBeInTheDocument();
});
test('EIP association opens its NAT gateway', async () => {
  mock(); const original = fetchApi.getMockImplementation()!;
  fetchApi.mockImplementation(async path => path.startsWith('/api/elastic-ips?') ? response({ items: [{ ...eip, association: { type: 'nat_gateway', id: nat.nat_gateway_id, link: '/nat-gateways/aws/111111111111/us-east-1/nat-demo' } }], total: 1 }) : original(path));
  setup('/elastic-ips');
  fireEvent.click(await screen.findByRole('link', { name: 'nat_gateway · nat-demo' }));
  expect(await screen.findByRole('heading', { name: 'NAT gateway details' })).toBeInTheDocument();
});
