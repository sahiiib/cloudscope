import { render, screen } from '@testing-library/react';
import { expect, test } from 'vitest';
import { instanceFixture } from '../test/instances';
import Summary from './Summary';

test.each(['aws', 'alibaba'] as const)('renders %s identity, resources and exact observation dates', provider => {
  const item = instanceFixture(provider); render(<Summary instance={item} />);
  for (const value of [item.name!, item.instance_id, 'Demo · 111111111111', 'example-key', 'Example Linux', item.last_observed]) expect(screen.getByText(value)).toBeInTheDocument();
  expect(screen.getByText('Last observed').nextElementSibling).toHaveTextContent(item.last_observed);
  expect(screen.getByText('CPU (vCPU)').nextElementSibling).toHaveTextContent('2');
  expect(screen.getByText('Memory (MiB)').nextElementSibling).toHaveTextContent(provider === 'aws' ? 'Not available' : '4096');
});
test('missing optional summary fields are explicit and missing presence is preserved', () => {
  render(<Summary instance={{ ...instanceFixture(), details: null, present: false, platform: null, zone: null, launch_time: null }} />);
  expect(screen.getByText('Missing')).toBeInTheDocument();
  for (const field of ['CPU (vCPU)', 'Memory (MiB)', 'Platform', 'Zone', 'Launch time']) expect(screen.getByText(field).nextElementSibling).toHaveTextContent('Not available');
});
