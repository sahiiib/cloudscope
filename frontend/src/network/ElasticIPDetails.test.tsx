import { screen } from '@testing-library/react';
import { expect, test } from 'vitest';
import { ApiError } from '../api/client';
import { fetchApi, response, setup, user } from '../test/auth';
import { eip } from '../test/network';
test('shows retained details, tags, raw and the association link', async () => {
  fetchApi.mockImplementation(async path => response(path === '/api/auth/me' ? user : { ...eip, present: false }));
  setup('/elastic-ips/aws/111111111111/us-east-1/eipalloc-demo');
  expect(await screen.findByText('Demo EIP', { selector: 'h2' })).toBeInTheDocument();
  expect(screen.getByText(/Missing from the last/)).toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'instance · i-demo' })).toHaveAttribute('href', eip.association!.link);
  expect(screen.getByText(/"AllocationId"/)).toBeInTheDocument();
  expect(screen.getByText(/"env": "test"/)).toBeInTheDocument();
});
test('unknown identity returns a not found message', async () => {
  fetchApi.mockImplementation(async path => { if (path === '/api/auth/me') return response(user); throw new ApiError(404); });
  setup('/elastic-ips/aws/111111111111/us-east-1/missing');
  expect(await screen.findByRole('alert')).toHaveTextContent('Elastic IP not found');
});
