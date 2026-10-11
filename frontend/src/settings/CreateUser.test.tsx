import { fireEvent, screen, waitFor } from '@testing-library/react';
import { expect, test, vi } from 'vitest';
import { ApiError } from '../api/client';
import { fetchApi, renderSettings, response } from '../test/settings';
import CreateUser from './CreateUser';

function fill() {
  fireEvent.change(screen.getByLabelText('New username'), { target: { value: 'new-user' } });
  fireEvent.change(screen.getByLabelText('Initial password'), { target: { value: 'password-placeholder' } });
  fireEvent.click(screen.getByLabelText('Administrator'));
  fireEvent.submit(screen.getByRole('form', { name: 'Create user' }));
}
test('creates a user with the chosen role and clears the form', async () => {
  fetchApi.mockResolvedValue(response({ id: 3 })); const created = vi.fn();
  renderSettings(<CreateUser onCreated={created} />); fill();
  await waitFor(() => expect(created).toHaveBeenCalledOnce());
  expect(fetchApi).toHaveBeenCalledWith('/api/users', expect.objectContaining({ body: '{"username":"new-user","password":"password-placeholder","is_admin":true}' }));
  expect(screen.getByLabelText('Initial password')).toHaveValue(''); expect(screen.getByLabelText('New username')).toHaveValue('');
});
test('duplicate user is actionable and the password is cleared on failure', async () => {
  fetchApi.mockRejectedValue(new ApiError(409)); renderSettings(<CreateUser onCreated={vi.fn()} />); fill();
  expect(await screen.findByRole('alert')).toHaveTextContent('already exists');
  expect(screen.getByLabelText('Initial password')).toHaveValue('');
  expect(screen.getByLabelText('New username')).toHaveValue('new-user');
});
