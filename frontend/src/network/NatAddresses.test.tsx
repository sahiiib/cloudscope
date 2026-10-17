import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { expect, test, vi } from 'vitest';
import NatAddresses from './NatAddresses';
import { nat } from '../test/nat';
test('private NAT addresses have no invented EIP link; allocation-only addresses link by ID', () => {
  const { rerender } = render(<MemoryRouter><NatAddresses nat={{ ...nat, addresses: [{ allocation_id: null, public_ip: null, private_ip: '10.0.0.1', network_interface_id: 'eni-demo' }] }} onStatus={vi.fn()} details /></MemoryRouter>);
  expect(screen.queryByRole('link')).not.toBeInTheDocument();
  expect(screen.getByText(/Private IP: 10.0.0.1/)).toBeInTheDocument();
  rerender(<MemoryRouter><NatAddresses nat={{ ...nat, addresses: [{ ...nat.addresses[0], public_ip: null }] }} onStatus={vi.fn()} /></MemoryRouter>);
  expect(screen.getByRole('link', { name: 'eipalloc-demo' })).toHaveAttribute('href', '/elastic-ips/aws/111111111111/us-east-1/eipalloc-demo');
});
