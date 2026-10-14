import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import ThemePicker from './ThemePicker';

afterEach(() => { localStorage.clear(); delete document.documentElement.dataset.theme; vi.restoreAllMocks(); });
test('choice applies immediately and persists across mounting', () => {
  const view = render(<ThemePicker />);
  fireEvent.change(screen.getByLabelText('Appearance'), { target: { value: 'dark' } });
  expect(document.documentElement).toHaveAttribute('data-theme', 'dark');
  expect(localStorage.getItem('cloudscope.theme')).toBe('dark');
  view.unmount(); render(<ThemePicker />);
  expect(screen.getByLabelText('Appearance')).toHaveValue('dark');
  fireEvent.change(screen.getByLabelText('Appearance'), { target: { value: 'light' } });
  expect(document.documentElement).toHaveAttribute('data-theme', 'light');
  fireEvent.change(screen.getByLabelText('Appearance'), { target: { value: 'system' } });
  expect(document.documentElement).toHaveAttribute('data-theme', 'system');
});
test('invalid preference defaults to system', () => {
  localStorage.setItem('cloudscope.theme', 'invalid'); render(<ThemePicker />);
  expect(screen.getByLabelText('Appearance')).toHaveValue('system');
});
test('unavailable storage does not prevent choosing a theme', () => {
  vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('blocked'); });
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('blocked'); });
  render(<ThemePicker />);
  fireEvent.change(screen.getByLabelText('Appearance'), { target: { value: 'dark' } });
  expect(document.documentElement).toHaveAttribute('data-theme', 'dark');
});
