import { fireEvent, screen } from '@testing-library/react';
import { expect, test } from 'vitest';
import { fetchApi, response, setup, user } from '../test/auth';

test('members see password/MFA settings but never fetch admin users', async () => {
  fetchApi.mockImplementation(async () => response({ ...user, is_admin: false }));
  setup('/settings'); await screen.findByRole('heading', { name: 'Settings' });
  expect(screen.getByRole('heading', { name: 'Change password' })).toBeInTheDocument();
  expect(screen.getByRole('heading', { name: 'Authenticator MFA' })).toBeInTheDocument();
  expect(screen.queryByRole('heading', { name: 'Users' })).not.toBeInTheDocument();
  expect(fetchApi.mock.calls.some(([path]) => path === '/api/users' || path === '/api/accounts')).toBe(false);
  expect(screen.queryByRole('heading', { name: 'Cloud accounts' })).not.toBeInTheDocument();
});
test('successful password change clears inventory cache and goes to login', async () => {
  fetchApi.mockImplementation(async path => path === '/api/auth/me' ? response({ ...user, is_admin: false }) : new Response(null, { status: 204 }));
  const client = setup('/settings'); await screen.findByRole('heading', { name: 'Settings' });
  client.setQueryData(['instances'], ['placeholder']);
  for (const label of ['Current password', 'New password', 'Confirm new password']) fireEvent.change(screen.getByLabelText(label), { target: { value: 'password-placeholder' } });
  fireEvent.submit(screen.getByRole('form', { name: 'Change password' }));
  expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument();
  expect(client.getQueryData(['instances'])).toBeUndefined();
});

test('admins see Cloud accounts and fetch the accounts list', async () => {
  fetchApi.mockImplementation(async path => response(path === '/api/auth/me' ? user : []));
  setup('/settings');
  expect(await screen.findByRole('heading', { name: 'Cloud accounts' })).toBeInTheDocument();
  expect(await screen.findByText('No cloud accounts yet.')).toBeInTheDocument();
  expect(fetchApi.mock.calls.some(([path]) => path === '/api/accounts')).toBe(true);
});
