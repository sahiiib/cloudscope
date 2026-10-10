import { act, fireEvent, render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, expect, test, vi } from 'vitest';
import { apiFetch, ApiError } from '../api/client';
import RunResults from './RunResults';

vi.mock('../api/client', async original => ({ ...await original<typeof import('../api/client')>(), apiFetch: vi.fn() }));
const fetchApi = vi.mocked(apiFetch);
function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><RunResults id={7} /></QueryClientProvider>);
}
afterEach(() => { vi.useRealTimers(); vi.resetAllMocks(); });

test('retries a detail failure independently', async () => {
  fetchApi.mockRejectedValue(new ApiError(503)); setup();
  await screen.findByRole('alert');
  fetchApi.mockImplementation(async () => new Response(JSON.stringify({ status: 'success', results: [] })));
  fireEvent.click(screen.getByRole('button', { name: 'Retry results' }));
  expect(await screen.findByText('No region results recorded.')).toBeInTheDocument();
});

test('refreshes running details and stops polling on completion', async () => {
  vi.useFakeTimers();
  let finished = false;
  fetchApi.mockImplementation(async () => new Response(JSON.stringify({ status: finished ? 'success' : 'running', results: [] })));
  setup(); await act(async () => { await vi.advanceTimersByTimeAsync(50); });
  expect(screen.getByText('Results will appear as regions finish.')).toBeInTheDocument();
  finished = true;
  await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
  expect(screen.getByText('No region results recorded.')).toBeInTheDocument();
  const count = fetchApi.mock.calls.length;
  await act(async () => { await vi.advanceTimersByTimeAsync(10000); });
  expect(fetchApi).toHaveBeenCalledTimes(count);
});
