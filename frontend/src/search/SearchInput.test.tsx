import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import SearchInput from './SearchInput';

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());
test('emits only the latest text after 300 ms', () => {
  const change = vi.fn();
  render(<SearchInput value="" revision="first" onChange={change} />);
  fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'web' } });
  act(() => vi.advanceTimersByTime(200));
  fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'web-1' } });
  act(() => vi.advanceTimersByTime(299));
  expect(change).not.toHaveBeenCalled();
  act(() => vi.advanceTimersByTime(1));
  expect(change).toHaveBeenCalledExactlyOnceWith('web-1');
});
test('revision change restores URL text and cancels pending input', () => {
  const change = vi.fn();
  const view = render(<SearchInput value="saved" revision="first" onChange={change} />);
  fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'discard' } });
  act(() => vi.advanceTimersByTime(200));
  view.rerender(<SearchInput value="restored" revision="second" onChange={change} />);
  expect(screen.getByRole('searchbox')).toHaveValue('restored');
  act(() => vi.advanceTimersByTime(1000));
  expect(change).not.toHaveBeenCalled();
});
