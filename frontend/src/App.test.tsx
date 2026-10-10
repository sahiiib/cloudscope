import { screen } from '@testing-library/react';
import { expect, test } from 'vitest';
import { fetchApi, response, setup, user } from './test/auth';

test('routes a signed-in visitor to Settings', async () => {
  fetchApi.mockResolvedValue(response(user));
  setup('/settings');
  expect(await screen.findByRole('heading', { name: 'Settings' })).toBeInTheDocument();
});
