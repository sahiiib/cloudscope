import { render, screen, within } from '@testing-library/react';
import { expect, test } from 'vitest';
import { instanceFixture } from '../test/instances';
import SecurityGroups from './SecurityGroups';

test.each(['aws', 'alibaba'] as const)('renders %s inbound and outbound rules', provider => {
  render(<SecurityGroups groups={instanceFixture(provider).details?.security_groups} />);
  const inbound = screen.getByRole('table', { name: 'sg-example inbound rules' });
  expect(within(inbound).getByText('10.0.0.0/16')).toBeInTheDocument();
  expect(within(inbound).getByText('443')).toBeInTheDocument();
  if (provider === 'alibaba') { expect(within(inbound).getByText('Drop')).toBeInTheDocument(); expect(within(inbound).getByText('1')).toBeInTheDocument(); }
  const outbound = screen.getByRole('table', { name: 'sg-example outbound rules' });
  expect(within(outbound).getByText('0.0.0.0/0')).toBeInTheDocument();
  expect(within(outbound).getByText('All')).toBeInTheDocument();
});
test('distinguishes absent rules from an empty rule list', () => {
  render(<SecurityGroups groups={[{ id: 'sg-example', description: 'Example', inbound: null, outbound: [] }]} />);
  expect(screen.getByText('Not available')).toBeInTheDocument();
  expect(screen.getByText('No rules')).toBeInTheDocument();
});
