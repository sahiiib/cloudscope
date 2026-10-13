import { screen } from '@testing-library/react';
import { expect, test } from 'vitest';
import { fetchApi, response, setup, user } from '../test/auth';

test('members cannot access cloud account administration on the direct route', async () => {
  fetchApi.mockResolvedValue(response({ ...user, is_admin: false })); setup('/accounts');
  expect(await screen.findByRole('alert')).toHaveTextContent('Only administrators');
  expect(screen.queryByRole('button', { name: 'Add cloud account' })).not.toBeInTheDocument();
});
test('administrators can reach accounts directly', async () => {
  fetchApi.mockImplementation(async path => response(path === '/api/auth/me' ? { ...user, is_admin: true } : []));
  setup('/accounts');
  expect(await screen.findByRole('button', { name: 'Add cloud account' })).toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'Accounts' })).toHaveAttribute('aria-current', 'page');
});
