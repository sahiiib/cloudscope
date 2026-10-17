import { screen } from '@testing-library/react';
import { expect, test } from 'vitest';
import { ApiError } from '../api/client';
import { fetchApi, response, setup, user } from '../test/auth';
import { nat } from '../test/nat';
test('shows missing data, tags, raw and EIP/private address details', async () => {
  fetchApi.mockImplementation(async path => response(path === '/api/auth/me' ? user : { ...nat, present: false }));
  setup('/nat-gateways/aws/111111111111/us-east-1/nat-demo');
  expect(await screen.findByText('Demo NAT', { selector: 'h2' })).toBeInTheDocument();
  expect(screen.getByText(/Missing from the last/)).toBeInTheDocument();
  expect(screen.getByRole('link', { name: '192.0.2.1' })).toHaveAttribute('href', '/elastic-ips/aws/111111111111/us-east-1/eipalloc-demo');
  expect(screen.getByText(/Private IP: 10.0.0.1/)).toBeInTheDocument();
  expect(screen.getByText(/"NatGatewayId"/)).toBeInTheDocument();
  expect(screen.getByText(/"env": "test"/)).toBeInTheDocument();
});
test('unknown NAT identity returns not found', async () => {
  fetchApi.mockImplementation(async path => { if (path === '/api/auth/me') return response(user); throw new ApiError(404); });
  setup('/nat-gateways/aws/111111111111/us-east-1/missing');
  expect(await screen.findByRole('alert')).toHaveTextContent('NAT gateway not found');
});
