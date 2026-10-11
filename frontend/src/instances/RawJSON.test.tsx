import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import RawJSON from './RawJSON';

afterEach(() => vi.unstubAllGlobals());
test.each([true, false])('copies exact JSON and reports clipboard success=%s', async success => {
  const raw = { InstanceId: 'i-example', nested: { literal: '<img src=x>' } };
  const write = success ? vi.fn().mockResolvedValue(undefined) : vi.fn().mockRejectedValue(new Error('Denied'));
  vi.stubGlobal('navigator', { clipboard: { writeText: write } });
  render(<RawJSON raw={raw} />);
  expect(document.querySelector('details')).not.toHaveAttribute('open');
  fireEvent.click(screen.getByText('Show provider payload'));
  fireEvent.click(screen.getByRole('button', { name: 'Copy JSON' }));
  expect(await screen.findByRole('status')).toHaveTextContent(success ? 'JSON copied.' : 'Unable to copy.');
  expect(write).toHaveBeenCalledWith(JSON.stringify(raw, null, 2));
  expect(document.querySelector('img')).toBeNull();
});
test('empty raw payload shows Not available', () => { render(<RawJSON raw={{}} />); expect(screen.getByText('Not available')).toBeInTheDocument(); });
