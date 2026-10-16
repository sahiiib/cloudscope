import { fireEvent, render, screen } from '@testing-library/react';
import { expect, test, vi } from 'vitest';
import FacetFilter from './FacetFilter';

test('retains a selected missing option with zero count and emits deselection', () => {
  const change = vi.fn();
  render(<FacetFilter label="Region" options={[]} selected={["eu-central-1"]} open onToggle={() => {}} onChange={change} />);
  const checkbox = screen.getByLabelText('eu-central-1 (0)');
  expect(checkbox).toBeChecked();
  fireEvent.click(checkbox);
  expect(change).toHaveBeenCalledWith('eu-central-1', false);
});

test('labels accounts with name and ID and emits selection', () => {
  const change = vi.fn();
  render(<FacetFilter label="Account" options={[{ value: '111111111111', count: 2 }]} selected={[]}
    names={{ "111111111111": "Demo" }} open onToggle={() => {}} onChange={change} />);
  fireEvent.click(screen.getByLabelText('Demo · 111111111111 (2)'));
  expect(change).toHaveBeenCalledWith('111111111111', true);
});
