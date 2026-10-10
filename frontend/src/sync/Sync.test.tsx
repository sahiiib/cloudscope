import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Outlet, Route, Routes } from 'react-router-dom';
import { afterEach, expect, test, vi } from 'vitest';
import { apiFetch, ApiError } from '../api/client';
import type { SyncRun } from '../api/types';
import Sync from './Sync';

vi.mock('../api/client', async original => ({ ...await original<typeof import('../api/client')>(), apiFetch: vi.fn() }));
const fetchApi = vi.mocked(apiFetch);
const run: SyncRun = { id: 7, started_at: '2026-01-01T00:00:00Z', finished_at: '2026-01-01T00:01:05Z', trigger: 'manual', status: 'partial', instances_seen: 11 };
function response(body: unknown) { return new Response(JSON.stringify(body)); }
function setup(admin = true) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/sync']}><Routes>
    <Route element={<Outlet context={{ id: 1, username: 'tester', is_admin: admin, mfa_enabled: false }} />}><Route path="/sync" element={<Sync />} /></Route>
  </Routes></MemoryRouter></QueryClientProvider>);
  return client;
}
afterEach(() => { vi.useRealTimers(); vi.resetAllMocks(); });

test('shows summaries, lazily expands account/region errors and hides admin control for members', async () => {
  fetchApi.mockImplementation(async path => path.includes('?') ? response([run]) : response({ ...run, results: [
    { provider: 'aws', account_id: '111111111111', region: 'eu-central-1', status: 'error', instances_seen: 0, duration_ms: 1200, error: 'Access denied' },
    { provider: 'alibaba', account_id: '222222222222', region: 'eu-central-1', status: 'success', instances_seen: 11, duration_ms: 2000, error: null },
  ] }));
  setup(false);
  expect(await screen.findByText('1m 5s')).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Sync now' })).not.toBeInTheDocument();
  expect(fetchApi).not.toHaveBeenCalledWith('/api/sync/runs/7', expect.anything());
  fireEvent.click(screen.getByRole('button', { name: 'Run #7' }));
  expect(await screen.findByText('Access denied')).toBeInTheDocument();
  expect(screen.getByText('Alibaba')).toBeInTheDocument();
  expect(screen.getByText('1.2s')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Run #7' })).toHaveAttribute('aria-expanded', 'true');
  fireEvent.click(screen.getByRole('button', { name: 'Run #7' }));
  expect(screen.queryByText('Access denied')).not.toBeInTheDocument();
});

test('admin starts a sync and the refreshed running state disables another request', async () => {
  let started = false;
  fetchApi.mockImplementation(async (_path, options) => {
    if (options?.method === 'POST') { started = true; return response({ status: 'accepted' }); }
    return response(started ? [{ ...run, finished_at: null, status: 'running' }] : []);
  });
  setup(); await screen.findByText('No sync runs yet.');
  fireEvent.click(screen.getByRole('button', { name: 'Sync now' }));
  expect(await screen.findByRole('button', { name: 'Sync running' })).toBeDisabled();
  expect(fetchApi).toHaveBeenCalledWith('/api/sync/runs', { method: 'POST' });
  expect(await screen.findByText('Sync requested. Progress appears below.')).toBeInTheDocument();
});

test.each([409, 503])('explains a %s start failure and keeps history usable', async status => {
  fetchApi.mockImplementation(async (_path, options) => {
    if (options?.method === 'POST') throw new ApiError(status);
    return response([run]);
  });
  setup(); await screen.findByText('1m 5s');
  fireEvent.click(screen.getByRole('button', { name: 'Sync now' }));
  expect(await screen.findByRole('alert')).toHaveTextContent(status === 409 ? 'already running' : 'unavailable');
  expect(screen.getByRole('button', { name: 'Run #7' })).toBeInTheDocument();
});

test('failed history can be retried', async () => {
  fetchApi.mockRejectedValue(new ApiError(503)); setup();
  await screen.findByRole('alert'); fetchApi.mockImplementation(async () => response([]));
  fireEvent.click(screen.getByRole('button', { name: 'Retry history' }));
  expect(await screen.findByText('No sync runs yet.')).toBeInTheDocument();
});

test('polls history and preserves cached runs on a failed refresh', async () => {
  fetchApi.mockImplementation(async () => response([run]));
  vi.useFakeTimers();
  setup();
  await act(async () => { await vi.advanceTimersByTimeAsync(50); });
  expect(screen.getByRole('button', { name: 'Run #7' })).toBeInTheDocument();
  const before = fetchApi.mock.calls.length;
  await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
  expect(fetchApi.mock.calls.length).toBeGreaterThan(before);
  vi.useRealTimers();
  fetchApi.mockRejectedValue(new ApiError(503));
  fireEvent.click(screen.getByRole('button', { name: 'Refresh' }));
  await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Showing the last received runs'));
  expect(screen.getByRole('button', { name: 'Run #7' })).toBeInTheDocument();
});
