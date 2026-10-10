import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, expect, test, vi } from 'vitest';
import App from './App';
import { ApiError, apiFetch } from './api/client';

vi.mock('./api/client', async (original) => ({ ...await original<typeof import('./api/client')>(), apiFetch: vi.fn() }));
const fetchApi = vi.mocked(apiFetch);
const user = { id: 1, username: 'tester', is_admin: true, mfa_enabled: false };
function response(body: unknown) { return new Response(JSON.stringify(body)); }
function setup(path = '/login') {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={[path]}><App /></MemoryRouter></QueryClientProvider>);
  return queryClient;
}
function signIn() {
  fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'tester' } });
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'test-password-placeholder' } });
  fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));
}
afterEach(() => vi.resetAllMocks());

test('successful login checks session and opens the protected shell', async () => {
  fetchApi.mockResolvedValueOnce(response({ mfa_required: false })).mockResolvedValue(response(user));
  setup(); signIn();
  expect(await screen.findByRole('navigation')).toBeInTheDocument();
  expect(screen.getByRole('heading', { name: 'Search' })).toBeInTheDocument();
  expect(fetchApi).toHaveBeenCalledWith('/api/auth/me', { redirectOnUnauthorized: false });
});

test('MFA does not expose protected pages before verification', async () => {
  fetchApi.mockResolvedValueOnce(response({ mfa_required: true }));
  setup(); signIn();
  const code = await screen.findByLabelText('Authenticator code');
  expect(screen.queryByRole('navigation')).not.toBeInTheDocument();
  expect(screen.queryByLabelText('Password')).not.toBeInTheDocument();
  fetchApi.mockResolvedValueOnce(response({ mfa_required: false })).mockResolvedValue(response(user));
  fireEvent.change(code, { target: { value: '123456' } });
  fireEvent.click(screen.getByRole('button', { name: 'Verify' }));
  expect(await screen.findByRole('navigation')).toBeInTheDocument();
  expect(fetchApi).toHaveBeenCalledWith('/api/auth/mfa/verify-login', expect.objectContaining({ body: JSON.stringify({ code: '123456' }) }));
});

test('bad credentials and rate limits appear inline', async () => {
  fetchApi.mockRejectedValueOnce(new ApiError(401));
  setup(); signIn();
  expect(await screen.findByRole('alert')).toHaveTextContent('Invalid username or password');
  expect(screen.getByLabelText('Password')).toHaveValue('');
  fetchApi.mockRejectedValueOnce(new ApiError(429));
  signIn();
  await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Too many attempts'));
});

test('invalid MFA code supports retry or returning to password login', async () => {
  fetchApi.mockResolvedValueOnce(response({ mfa_required: true }));
  setup(); signIn();
  fireEvent.change(await screen.findByLabelText('Authenticator code'), { target: { value: '123456' } });
  fetchApi.mockRejectedValueOnce(new ApiError(401));
  fireEvent.click(screen.getByRole('button', { name: 'Verify' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Invalid code or expired');
  fireEvent.click(screen.getByRole('button', { name: 'Back to sign in' }));
  expect(screen.getByLabelText('Password')).toHaveValue('');
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
});

test('guard redirects unauthenticated visitors and preserves their destination', async () => {
  fetchApi.mockRejectedValueOnce(new ApiError(401));
  setup('/sync');
  await screen.findByRole('heading', { name: 'Sign in' });
  fetchApi.mockResolvedValueOnce(response({ mfa_required: false })).mockResolvedValue(response(user));
  signIn();
  expect(await screen.findByRole('heading', { name: 'Sync' })).toBeInTheDocument();
});

test('session outage offers retry without showing protected content', async () => {
  fetchApi.mockRejectedValueOnce(new ApiError(503));
  setup('/settings');
  expect(await screen.findByRole('alert')).toHaveTextContent('Unable to check');
  expect(screen.queryByRole('navigation')).not.toBeInTheDocument();
  fetchApi.mockResolvedValue(response(user));
  fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
  expect(await screen.findByRole('heading', { name: 'Settings' })).toBeInTheDocument();
});

test('logout clears cached inventory and returns to login', async () => {
  fetchApi.mockResolvedValue(response(user));
  const cache = setup('/');
  cache.setQueryData(['instances'], ['cached-placeholder']);
  fireEvent.click(await screen.findByText('tester'));
  fetchApi.mockResolvedValueOnce(new Response(null, { status: 204 }));
  fireEvent.click(screen.getByRole('button', { name: 'Log out' }));
  expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument();
  expect(cache.getQueryData(['instances'])).toBeUndefined();
});
