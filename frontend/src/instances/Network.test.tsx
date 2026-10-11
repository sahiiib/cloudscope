import { render, screen, within } from '@testing-library/react';
import { expect, test } from 'vitest';
import { instanceFixture } from '../test/instances';
import Network from './Network';

test.each(['aws', 'alibaba'] as const)('renders %s network and interface fields', provider => {
  render(<Network instance={instanceFixture(provider)} />);
  expect(screen.getByRole('heading', { name: provider === 'aws' ? 'Subnet' : 'vSwitch' })).toBeInTheDocument();
  expect(screen.getByText('Example VPC')).toBeInTheDocument();
  expect(screen.getByText('10.0.0.0/16')).toBeInTheDocument();
  const table = screen.getByRole('table', { name: 'Network interfaces' });
  for (const value of ['eni-example', '10.0.0.1, 10.0.0.2', '192.0.2.1', 'sg-example']) expect(within(table).getByText(value)).toBeInTheDocument();
});
test('retains top-level network IDs without enriched details', () => {
  render(<Network instance={{ ...instanceFixture(), details: {} }} />);
  expect(screen.getByText('vpc-example')).toBeInTheDocument();
  expect(screen.getByText('subnet-example')).toBeInTheDocument();
  expect(screen.getAllByText('Not available').length).toBeGreaterThan(0);
});
