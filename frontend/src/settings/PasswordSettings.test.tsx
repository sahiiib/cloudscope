import { fireEvent, screen, waitFor } from '@testing-library/react';
import { expect, test, vi } from 'vitest';
import { ApiError } from '../api/client';
import { fetchApi, renderSettings } from '../test/settings';
import PasswordSettings from './PasswordSettings';

function fill(confirm = 'new-password-placeholder') {
  fireEvent.change(screen.getByLabelText('Current password'), { target: { value: 'current-password-placeholder' } });
  fireEvent.change(screen.getByLabelText('New password'), { target: { value: 'new-password-placeholder' } });
  fireEvent.change(screen.getByLabelText('Confirm new password'), { target: { value: confirm } });
  fireEvent.submit(screen.getByRole('form', { name: 'Change password' }));
}
test('changes password, clears inputs and ends the session without caching credentials', async () => {
  fetchApi.mockResolvedValue(new Response(null, { status: 204 }));
  const end = vi.fn(); const client = renderSettings(<PasswordSettings onSessionEnd={end} />);
  fill(); await waitFor(() => expect(end).toHaveBeenCalledOnce());
  expect(fetchApi).toHaveBeenCalledWith('/api/auth/password', expect.objectContaining({
    method: 'POST', redirectOnUnauthorized: false, body: JSON.stringify({ current_password: 'current-password-placeholder', new_password: 'new-password-placeholder' }),
  }));
  expect(screen.getByLabelText('Current password')).toHaveValue('');
  expect(screen.getByLabelText('New password')).toHaveValue('');
  expect(client.getMutationCache().getAll().every(mutation => mutation.state.variables === undefined)).toBe(true);
});
test('rejects mismatched confirmation before sending a request', () => {
  renderSettings(<PasswordSettings onSessionEnd={vi.fn()} />); fill('different-placeholder');
  expect(screen.getByRole('alert')).toHaveTextContent('do not match'); expect(fetchApi).not.toHaveBeenCalled();
});
test('wrong current password stays inline and clears submitted secrets', async () => {
  fetchApi.mockRejectedValue(new ApiError(401)); const end = vi.fn();
  renderSettings(<PasswordSettings onSessionEnd={end} />); fill();
  expect(await screen.findByRole('alert')).toHaveTextContent('not accepted');
  expect(end).not.toHaveBeenCalled(); expect(screen.getByLabelText('Current password')).toHaveValue('');
});
