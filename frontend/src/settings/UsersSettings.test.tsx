import { fireEvent, screen, waitFor } from '@testing-library/react';
import { expect, test, vi } from 'vitest';
import { ApiError } from '../api/client';
import { fetchApi, renderSettings, response } from '../test/settings';
import UsersSettings from './UsersSettings';

const member = { id: 2, username: 'member', is_admin: false, is_active: true, mfa_enabled: true, created_at: '2026-01-01T00:00:00Z', last_login_at: null };
test('confirms deactivation, refreshes list and can reset MFA', async () => {
  let active = true; let mfa = true;
  fetchApi.mockImplementation(async (path, options) => {
    if (options?.method === 'PATCH') active = false;
    if (path.endsWith('/reset-mfa')) mfa = false;
    return response([{ ...member, is_active: active, mfa_enabled: mfa }]);
  });
  renderSettings(<UsersSettings currentUserId={1} onSessionEnd={vi.fn()} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Deactivate member' }));
  expect(fetchApi.mock.calls.some(([, options]) => options?.method === 'PATCH')).toBe(false);
  fireEvent.click(screen.getByRole('button', { name: 'Confirm change' }));
  expect(await screen.findByRole('button', { name: 'Reactivate member' })).toBeInTheDocument();
  expect(fetchApi).toHaveBeenCalledWith('/api/users/2', expect.objectContaining({ method: 'PATCH', body: '{"is_active":false}' }));
  fireEvent.click(screen.getByRole('button', { name: 'Reset MFA for member' }));
  fireEvent.click(screen.getByRole('button', { name: 'Confirm change' }));
  await screen.findByText('Disabled');
  expect(fetchApi).toHaveBeenCalledWith('/api/users/2/reset-mfa', { method: 'POST' });
});
test('last-admin conflict stays inline and cancellation does not mutate', async () => {
  fetchApi.mockImplementation(async (_path, options) => {
    if (options?.method === 'PATCH') throw new ApiError(409);
    return response([{ ...member, id: 1, is_admin: true }]);
  });
  const end = vi.fn(); renderSettings(<UsersSettings currentUserId={1} onSessionEnd={end} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Deactivate member' }));
  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
  expect(fetchApi).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole('button', { name: 'Deactivate member' }));
  fireEvent.click(screen.getByRole('button', { name: 'Confirm change' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('last active administrator');
  expect(end).not.toHaveBeenCalled();
});
test('resetting own MFA ends the current session', async () => {
  fetchApi.mockImplementation(async () => response([{ ...member, id: 1 }]));
  const end = vi.fn(); renderSettings(<UsersSettings currentUserId={1} onSessionEnd={end} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Reset MFA for member' }));
  expect(screen.getByText('This will sign you out.')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Confirm change' }));
  await waitFor(() => expect(end).toHaveBeenCalledOnce());
});

test('SSO users have managed roles and no local MFA action; SSO mode creates local admins', async () => {
  fetchApi.mockImplementation(async (_path, options) => response(options?.method === 'POST' ? {} : [{ ...member, is_sso: true, is_admin: true }]));
  const client = renderSettings(<UsersSettings currentUserId={1} onSessionEnd={vi.fn()} />);
  client.setQueryData(['auth', 'config'], { local_login: true, sso: { enabled: true, label: 'Sign in with Keycloak' } });
  expect(await screen.findByRole('columnheader', { name: 'Sign-in' })).toBeInTheDocument();
  expect(screen.getByText('SSO')).toBeInTheDocument();
  expect(screen.getByText('Admin (Keycloak)')).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Reset MFA for member' })).not.toBeInTheDocument();
  expect(await screen.findByText(/Creates a local administrator/)).toBeInTheDocument();
  expect(screen.queryByRole('checkbox', { name: 'Administrator' })).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('New username'), { target: { value: 'emergency-admin' } });
  fireEvent.change(screen.getByLabelText('Initial password'), { target: { value: 'password-placeholder' } });
  fireEvent.submit(screen.getByRole('form', { name: 'Create user' }));
  await waitFor(() => expect(fetchApi).toHaveBeenCalledWith('/api/users', expect.objectContaining({ body: JSON.stringify({ username: 'emergency-admin', password: 'password-placeholder', is_admin: true }) })));
});
