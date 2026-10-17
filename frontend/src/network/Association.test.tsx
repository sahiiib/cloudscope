import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { expect, test, vi } from 'vitest';
import Association from './Association';
test('unresolved ENIs are text with copy, available addresses have no association', () => {
  const { rerender } = render(<MemoryRouter><Association association={{ type: 'network_interface', id: 'eni-demo', link: null }} onStatus={vi.fn()} /></MemoryRouter>);
  expect(screen.queryByRole('link')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Copy associated ID eni-demo' })).toBeInTheDocument();
  rerender(<MemoryRouter><Association association={null} onStatus={vi.fn()} /></MemoryRouter>);
  expect(screen.getByText('Not associated')).toBeInTheDocument();
});
