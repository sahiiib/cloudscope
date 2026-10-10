import { fireEvent, screen, waitFor } from '@testing-library/react';
import { expect, test } from 'vitest';
import { ApiError } from '../api/client';
import { fetchApi, response, setup, signIn, user } from '../test/auth';

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


test('cached user keeps the shell visible after a failed refetch', async () => {
  fetchApi.mockImplementation(async path => {
    if (path === '/api/auth/me') throw new ApiError(503);
    return response([]);
  });
  const cache = setup('/sync', true);
  expect(screen.getByRole('navigation')).toBeInTheDocument();
  await waitFor(() => expect(cache.getQueryState(['auth', 'me'])?.status).toBe('error'));
  expect(screen.getByRole('navigation')).toBeInTheDocument();
  expect(screen.getByRole('heading', { name: 'Sync' })).toBeInTheDocument();
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
});
