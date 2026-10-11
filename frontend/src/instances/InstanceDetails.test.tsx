import { fireEvent, render, screen, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, expect, test, vi } from 'vitest';
import { apiFetch, ApiError } from '../api/client';
import { instanceFixture } from '../test/instances';
import App from '../App';
import InstanceDetails from './InstanceDetails';

vi.mock('../api/client', async original => ({ ...await original<typeof import('../api/client')>(), apiFetch: vi.fn() }));
const fetchApi = vi.mocked(apiFetch);
function response(body: unknown) { return new Response(JSON.stringify(body)); }
function setup(provider = 'aws') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[`/instances/${provider}/111111111111/eu-central-1/i-0123456789abcdef0`]}><Routes>
    <Route path="/instances/:provider/:account/:region/:id" element={<InstanceDetails />} />
  </Routes></MemoryRouter></QueryClientProvider>);
}
afterEach(() => vi.resetAllMocks());

test.each(['aws', 'alibaba'] as const)('renders all five sections from the %s fixture', async provider => {
  fetchApi.mockImplementation(async () => response(instanceFixture(provider))); setup(provider);
  await screen.findByRole('region', { name: 'Summary' });
  for (const name of ['Summary', 'Tags', 'Network', 'Security groups', 'Raw JSON']) expect(screen.getByRole('region', { name })).toBeInTheDocument();
  expect(within(screen.getByRole('region', { name: 'Summary' })).getByText(`${provider}-web`)).toBeInTheDocument();
  expect(within(screen.getByRole('region', { name: 'Tags' })).getByText('infra')).toBeInTheDocument();
  expect(fetchApi).toHaveBeenCalledWith(`/api/instances/${provider}/111111111111/eu-central-1/i-0123456789abcdef0`, expect.objectContaining({ signal: expect.any(AbortSignal) }));
  fireEvent.click(screen.getByText('Show provider payload'));
  expect(screen.getByText(/"InstanceId"/)).toBeInTheDocument();
});
test('missing enrichment and raw payload show Not available, while a missing instance remains visible', async () => {
  fetchApi.mockImplementation(async () => response({ ...instanceFixture(), present: false, details: null, raw: null, tags: {}, vpc_id: null, subnet_id: null })); setup();
  await screen.findByText(/Missing — this instance/);
  for (const name of ['Tags', 'Network', 'Security groups', 'Raw JSON']) expect(within(screen.getByRole('region', { name })).getAllByText('Not available').length).toBeGreaterThan(0);
});
test('404 displays not found rather than missing inventory', async () => {
  fetchApi.mockRejectedValue(new ApiError(404)); setup();
  expect(await screen.findByRole('alert')).toHaveTextContent('Instance not found.');
  expect(screen.queryByRole('region', { name: 'Summary' })).not.toBeInTheDocument();
});
test('a failed request can be retried', async () => {
  fetchApi.mockRejectedValueOnce(new ApiError(503)).mockImplementation(async () => response(instanceFixture())); setup();
  expect(await screen.findByRole('alert')).toHaveTextContent('Unable to load');
  fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
  expect(await screen.findByRole('region', { name: 'Summary' })).toBeInTheDocument();
});


test('search result link opens the protected details route in the application', async () => {
  fetchApi.mockImplementation(async path => {
    if (path === '/api/auth/me') return response({ id: 1, username: 'tester', is_admin: false, mfa_enabled: false });
    if (path.startsWith('/api/instances/facets')) return response({ providers: [], accounts: [], regions: [], states: [] });
    if (path === '/api/accounts') return response([]);
    if (path.startsWith('/api/instances?')) return response({ items: [instanceFixture()], total: 1, page: 1, page_size: 50 });
    return response(instanceFixture());
  });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><MemoryRouter><App /></MemoryRouter></QueryClientProvider>);
  fireEvent.click(await screen.findByRole('link', { name: 'aws-web' }));
  expect(await screen.findByRole('region', { name: 'Summary' })).toBeInTheDocument();
  expect(screen.getByRole('navigation', { name: 'Main navigation' })).toBeInTheDocument();
});

test('invalid provider does not make an API request', async () => {
  setup('unknown');
  expect(screen.getByRole('alert')).toHaveTextContent('Instance not found.');
  expect(fetchApi).not.toHaveBeenCalled();
});
