import { fireEvent, render, screen } from '@testing-library/react';
import { expect, test, vi } from 'vitest';
import RegionPicker from './RegionPicker';

test('shows resource counts and ticked means scan, with excluded regions unticked', () => {
  const change = vi.fn();
  render(<RegionPicker regions={[
    { region: 'eu-central-1', instances: 12, load_balancers: 3, excluded: false },
    { region: 'us-west-2', instances: 0, load_balancers: 0, excluded: true },
  ]} excluded={['us-west-2']} onChange={change} />);
  expect(screen.getByText('eu-central-1 · 12 instances · 3 load balancers')).toBeInTheDocument();
  expect(screen.getByRole('checkbox', { name: 'Scan eu-central-1' })).toBeChecked();
  expect(screen.getByRole('checkbox', { name: 'Scan us-west-2' })).not.toBeChecked();
  fireEvent.click(screen.getByRole('checkbox', { name: 'Scan eu-central-1' }));
  expect(change).toHaveBeenLastCalledWith('eu-central-1', false);
  fireEvent.click(screen.getByRole('checkbox', { name: 'Scan us-west-2' }));
  expect(change).toHaveBeenLastCalledWith('us-west-2', true);
});
