import { fireEvent, screen, waitFor } from '@testing-library/react';
import { expect, test } from 'vitest';
import { ApiError } from '../api/client';
import { fetchApi, response, setup, signIn, user } from '../test/auth';

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

