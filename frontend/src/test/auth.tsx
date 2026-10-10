import { fireEvent, render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, vi } from 'vitest';
import App from '../App';
import { apiFetch } from '../api/client';

vi.mock('../api/client', async (original) => ({ ...await original<typeof import('../api/client')>(), apiFetch: vi.fn() }));
export const fetchApi = vi.mocked(apiFetch);
export const user = { id: 1, username: 'tester', is_admin: true, mfa_enabled: false };
export function response(body: unknown) { return new Response(JSON.stringify(body)); }
export function setup(path = '/login', cachedUser = false) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  if (cachedUser) queryClient.setQueryData(['auth', 'me'], user);
  render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={[path]}><App /></MemoryRouter></QueryClientProvider>);
  return queryClient;
}
export function signIn() {
  fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'tester' } });
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'test-password-placeholder' } });
  fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));
}
afterEach(() => vi.resetAllMocks());

