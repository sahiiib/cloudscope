import { fireEvent, screen, waitFor } from '@testing-library/react';
import { expect, test } from 'vitest';
import { ApiError } from '../api/client';
import { fetchApi, response, setup, signIn, user } from '../test/auth';

test('successful login checks session and opens the protected shell', async () => {
  fetchApi.mockResolvedValueOnce(response({ mfa_required: false })).mockResolvedValue(response(user));
  setup(); signIn();
  expect(await screen.findByRole('navigation')).toBeInTheDocument();
  expect(screen.getByRole('heading', { name: 'Instances' })).toBeInTheDocument();
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


test('loads public SSO config and exposes the local admin form on demand', async () => {
  fetchApi.mockResolvedValue(response({ local_login: true, sso: { enabled: true, label: 'Sign in with Keycloak' } }));
  setup('/login', false, null);
  expect(screen.getByRole('status')).toHaveTextContent('Loading sign-in options');
  const sso = await screen.findByRole('link', { name: 'Sign in with Keycloak' });
  expect(sso).toHaveAttribute('href', '/api/auth/oidc/login?next=%2F');
  expect(screen.queryByLabelText('Password')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('link', { name: 'Admin sign-in' }));
  expect(screen.getByLabelText('Password')).toBeInTheDocument();
  expect(fetchApi).toHaveBeenCalledWith('/api/auth/config', { redirectOnUnauthorized: false });
});

test.each([['sso', 'Unable to sign in with Keycloak'], ['not-authorized', 'Not authorized']])('SSO callback error %s is shown', (error, message) => {
  setup(`/login?error=${error}`);
  expect(screen.getByRole('alert')).toHaveTextContent(message);
});

test('SSO preserves a protected destination without an external redirect', async () => {
  fetchApi.mockRejectedValueOnce(new ApiError(401));
  setup('/sync', false, { local_login: true, sso: { enabled: true, label: 'Sign in with Keycloak' } });
  expect(await screen.findByRole('link', { name: 'Sign in with Keycloak' })).toHaveAttribute('href', '/api/auth/oidc/login?next=%2Fsync');
});

test('configuration failure offers retry and does not guess sign-in methods', async () => {
  fetchApi.mockRejectedValueOnce(new ApiError(503));
  setup('/login', false, null);
  expect(await screen.findByRole('alert')).toHaveTextContent('Unable to load sign-in options');
  expect(screen.queryByLabelText('Password')).not.toBeInTheDocument();
  fetchApi.mockResolvedValue(response({ local_login: true, sso: { enabled: false, label: 'Sign in with Keycloak' } }));
  fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
  expect(await screen.findByLabelText('Password')).toBeInTheDocument();
});
