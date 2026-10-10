import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import { afterEach, expect, test, vi } from 'vitest';
import { apiFetch, ApiError } from '../api/client';
import type { InstanceSummary } from '../api/types';
import Search from './Search';

vi.mock('../api/client', async original => ({ ...await original<typeof import('../api/client')>(), apiFetch: vi.fn() }));
const fetchApi = vi.mocked(apiFetch);
const item: InstanceSummary = {
  provider: 'aws', account_id: '111111111111', account_name: 'Demo', region: 'eu-central-1',
  instance_id: 'i-0123456789abcdef0', name: 'web-1', state: 'running', instance_type: 't3.small',
  private_ips: ['10.0.0.1'], public_ips: [], tags: { env: 'test', team: 'infra', app: 'web', extra: 'tag' },
  launch_time: '2026-01-01T00:00:00Z', last_observed: '2026-01-02T00:00:00Z', present: true,
};
const facets = { providers: [{ value: 'aws', count: 80 }, { value: 'alibaba', count: 2 }], accounts: [{ value: '111111111111', count: 80 }], regions: [{ value: 'eu-central-1', count: 80 }], states: [{ value: 'running', count: 80 }] };
function response(body: unknown) { return new Response(JSON.stringify(body)); }
function mockData(items = [item], total = 80) {
  fetchApi.mockImplementation(async path => {
    if (path.startsWith('/api/instances/facets')) return response(facets);
    if (path === '/api/accounts') return response([{ account_id: item.account_id, name: 'Demo' }]);
    return response({ items, total, page: 1, page_size: 50 });
  });
}
function Location() {
  const location = useLocation(); const navigate = useNavigate();
  return <><output aria-label="Location">{location.pathname}{location.search}</output><button onClick={() => navigate(-1)}>Back</button></>;
}
function setup(path = '/') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}><Location /><Routes>
    <Route path="/" element={<Search />} /><Route path="/instances/:provider/:account/:region/:id" element={<h1>Instance details</h1>} />
  </Routes></MemoryRouter></QueryClientProvider>);
}
function lastListQuery() {
  const call = fetchApi.mock.calls.filter(([path]) => path.startsWith('/api/instances?')).at(-1);
  return new URLSearchParams(call?.[0].split('?')[1]);
}
afterEach(() => vi.resetAllMocks());

test('restores URL filters, renders every default column and copies/navigates to an instance', async () => {
  mockData(); setup('/?q=web&provider=aws&region=eu-central-1&include_missing=true');
  expect(await screen.findByRole('link', { name: 'web-1' })).toHaveAttribute('href', '/instances/aws/111111111111/eu-central-1/i-0123456789abcdef0');
  expect(screen.getByLabelText('Search instances')).toHaveValue('web');
  expect(screen.getByLabelText('Show terminated/missing')).toBeChecked();
  expect(lastListQuery().get('q')).toBe('web');
  expect(lastListQuery().get('page_size')).toBe('50');
  expect(screen.getAllByRole('columnheader')).toHaveLength(11);
  expect(screen.getByText('10.0.0.1')).toBeInTheDocument();
  expect(screen.getByText('+1')).toHaveAttribute('title', 'extra=tag');
  expect(document.querySelector('time')).toHaveAttribute('title', '2026-01-01T00:00:00.000Z');
  const copy = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: copy } });
  fireEvent.click(screen.getByRole('button', { name: `Copy ${item.instance_id}` }));
  await screen.findByText('Instance ID copied.');
  expect(copy).toHaveBeenCalledWith(item.instance_id);
  fireEvent.click(screen.getByText('t3.small'));
  expect(await screen.findByRole('heading', { name: 'Instance details' })).toBeInTheDocument();
});

test('debounces typing, preserves multiple facet values and updates URL and API', async () => {
  mockData(); setup('/?page=2');
  await screen.findByText('web-1');
  fireEvent.change(screen.getByLabelText('Search instances'), { target: { value: 'database' } });
  expect(lastListQuery().get('q')).toBeNull();
  await waitFor(() => expect(lastListQuery().get('q')).toBe('database'));
  expect(lastListQuery().get('page')).toBe('1');
  fireEvent.click(screen.getByText('Provider', { selector: 'summary' }));
  fireEvent.click(await screen.findByLabelText('aws (80)'));
  fireEvent.click(await screen.findByLabelText('alibaba (2)'));
  await waitFor(() => expect(lastListQuery().getAll('provider')).toEqual(['aws', 'alibaba']));
  expect(screen.getByLabelText('Location')).toHaveTextContent('provider=aws&provider=alibaba');
  fireEvent.click(screen.getByLabelText('Show terminated/missing'));
  await waitFor(() => expect(lastListQuery().get('include_missing')).toBe('true'));
  fireEvent.click(screen.getByRole('button', { name: 'Back' }));
  await waitFor(() => expect(screen.getByLabelText('Show terminated/missing')).not.toBeChecked());
});

test('sorts both ways, pages, changes page size and resets page for filters', async () => {
  mockData(); setup(); await screen.findByText('web-1');
  fireEvent.click(screen.getByRole('button', { name: 'Next' }));
  await waitFor(() => expect(lastListQuery().get('page')).toBe('2'));
  fireEvent.click(await screen.findByRole('button', { name: 'Account' }));
  await waitFor(() => expect(lastListQuery().get('sort')).toBe('account'));
  expect(lastListQuery().get('page')).toBe('1');
  fireEvent.click(await screen.findByRole('button', { name: 'Account ↑' }));
  await waitFor(() => expect(lastListQuery().get('sort')).toBe('-account'));
  fireEvent.change(await screen.findByLabelText('Rows per page'), { target: { value: '100' } });
  await waitFor(() => expect(lastListQuery().get('page_size')).toBe('100'));
  expect(await screen.findByRole('button', { name: 'Next' })).toBeDisabled();
});

test('shows empty and retryable failure states', async () => {
  fetchApi.mockRejectedValue(new ApiError(503)); setup();
  const error = await screen.findByText('Unable to load instances.');
  mockData([], 0);
  fireEvent.click(within(error).getByRole('button', { name: 'Retry' }));
  expect(await screen.findByText('No instances match this search.')).toBeInTheDocument();
});

test('clearing filters cancels an uncommitted search and restores the input', async () => {
  mockData(); setup(); await screen.findByText('web-1');
  fireEvent.change(screen.getByLabelText('Search instances'), { target: { value: 'discard me' } });
  fireEvent.click(screen.getByRole('button', { name: 'Clear filters' }));
  expect(screen.getByLabelText('Search instances')).toHaveValue('');
  await new Promise(resolve => setTimeout(resolve, 350));
  expect(lastListQuery().get('q')).toBeNull();
});
