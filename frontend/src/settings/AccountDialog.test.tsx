import { fireEvent, screen, waitFor } from '@testing-library/react';
import { expect, test } from 'vitest';
import { fetchApi, renderSettings, response } from '../test/settings';
import CloudAccounts from './CloudAccounts';

function setup() {
  fetchApi.mockImplementation(async path => response(path.endsWith('/capabilities') ? { dedicated_credentials: false } : []));
  renderSettings(<CloudAccounts />);
}

test('add opens a named modal, traps keyboard focus, closes on Escape and restores opener', async () => {
  setup();
  const opener = await screen.findByRole('button', { name: 'Add cloud account' });
  // Safari mouse clicks can leave focus on body; restore the explicit opener.
  expect(document.activeElement).toBe(document.body);
  fireEvent.click(opener);
  const dialog = screen.getByRole('dialog', { name: 'Add cloud account' });
  expect(dialog).toHaveAttribute('open');
  expect(document.getElementById(dialog.getAttribute('aria-labelledby')!)).toHaveTextContent('Add cloud account');
  const first = screen.getByLabelText('Provider');
  const last = screen.getByRole('button', { name: 'Cancel' });
  first.focus(); fireEvent.keyDown(first, { key: 'Tab', shiftKey: true });
  expect(last).toHaveFocus();
  fireEvent.keyDown(last, { key: 'Tab' }); expect(first).toHaveFocus();
  fireEvent(dialog, new Event('cancel', { bubbles: false, cancelable: true }));
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  await waitFor(() => expect(opener).toHaveFocus());
});

test('dirty modal asks before discarding and Keep editing retains the inputs', async () => {
  setup();
  const opener = await screen.findByRole('button', { name: 'Add cloud account' });
  // Safari mouse clicks can leave focus on body; restore the explicit opener.
  expect(document.activeElement).toBe(document.body);
  fireEvent.click(opener);
  fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Unsaved' } });
  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
  expect(screen.getByRole('group', { name: 'Discard unsaved changes' })).toHaveFocus();
  fireEvent.click(screen.getByRole('button', { name: 'Keep editing' }));
  expect(screen.getByLabelText('Name')).toHaveValue('Unsaved');
  fireEvent(screen.getByRole('dialog'), new Event('cancel', { cancelable: true }));
  fireEvent.click(screen.getByRole('button', { name: 'Discard changes' }));
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  await waitFor(() => expect(opener).toHaveFocus());
  expect(fetchApi.mock.calls.some(([, options]) => options?.method === 'POST')).toBe(false);
});
