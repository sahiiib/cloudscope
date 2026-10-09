import { render, screen } from '@testing-library/react';
import { expect, test } from 'vitest';
import App from './App';

test('renders the Cloudscope landing page', () => {
  render(<App />);
  expect(screen.getByRole('heading', { name: 'Cloudscope', level: 1 })).toBeInTheDocument();
});
