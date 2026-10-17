import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { afterEach, expect, test, vi } from 'vitest';
import type { InstanceSummary } from '../api/types';
import InstanceTable from './InstanceTable';

const navigate = vi.hoisted(() => vi.fn());
vi.mock('react-router-dom', async original => ({ ...await original<typeof import('react-router-dom')>(), useNavigate: () => navigate }));
const item: InstanceSummary = {
  provider: 'aws', account_id: '111111111111', account_name: 'Demo', account_alias: 'demo-alias', region: 'eu-central-1',
  instance_id: 'i-0123456789abcdef0', name: 'web-1', state: 'stopped', instance_type: 't3.small',
  private_ips: [], public_ips: [], tags: { a: '1', b: '2', c: '3', d: '4', e: '5' },
  launch_time: null, last_observed: '2026-01-01T00:00:00Z', present: false,
};
function Location() { return <output aria-label="Location">{useLocation().pathname}</output>; }
function setup(sort = 'name', onSort = vi.fn()) {
  render(<MemoryRouter><Location /><InstanceTable items={[item]} sort={sort} onSort={onSort} /></MemoryRouter>);
}
afterEach(() => { vi.clearAllMocks(); vi.unstubAllGlobals(); });

test.each([['name', 'ascending'], ['-name', 'descending']])('exposes aria-sort for %s and renders missing/tag overflow', (sort, direction) => {
  const onSort = vi.fn(); setup(sort, onSort);
  expect(screen.getByRole('columnheader', { name: /Name/ })).toHaveAttribute('aria-sort', direction);
  expect(screen.getByRole('columnheader', { name: 'Region' })).toHaveAttribute('aria-sort', 'none');
  fireEvent.click(screen.getByRole('button', { name: 'Region' }));
  expect(onSort).toHaveBeenCalledWith('region');
  expect(screen.getByText('Missing')).toBeInTheDocument();
  expect(screen.getByText('+2')).toHaveAttribute('title', 'd=4\ne=5');
  expect(screen.queryByText('d=4')).not.toBeInTheDocument();
  expect(screen.getByRole('img', { name: 'stopped' })).toHaveAttribute('title', 'stopped');
  expect(screen.queryByText('Copy')).not.toBeInTheDocument();
});

test.each([true, false])('copy success=%s keeps row navigation untouched', async success => {
  const copy = success ? vi.fn().mockResolvedValue(undefined) : vi.fn().mockRejectedValue(new Error('Denied'));
  vi.stubGlobal('navigator', { clipboard: { writeText: copy } });
  setup(); fireEvent.click(screen.getByRole('button', { name: `Copy ${item.instance_id}` }));
  await screen.findByText(success ? 'Instance ID copied.' : 'Unable to copy. Select and copy the instance ID.');
  expect(copy).toHaveBeenCalledWith(item.instance_id);
  expect(navigate).not.toHaveBeenCalled();
  expect(screen.getByLabelText('Location')).toHaveTextContent(/^\/$/);
});

test('links use their own navigation without triggering the row handler', () => {
  setup(); fireEvent.click(screen.getByRole('link', { name: 'web-1' }));
  expect(navigate).not.toHaveBeenCalled();
  expect(screen.getByLabelText('Location')).toHaveTextContent('/instances/aws/111111111111/eu-central-1/i-0123456789abcdef0');
  fireEvent.click(screen.getByText('t3.small'));
  expect(navigate).toHaveBeenCalledExactlyOnceWith('/instances/aws/111111111111/eu-central-1/i-0123456789abcdef0');
});

test.each(['aws', 'alibaba'] as const)('shows separate account fields for %s and copies the account ID', async provider => {
  const accountId = provider === 'aws' ? '111111111111' : '1111111111111111';
  const copy = vi.fn().mockResolvedValue(undefined);
  vi.stubGlobal('navigator', { clipboard: { writeText: copy } });
  render(<MemoryRouter><InstanceTable items={[{ ...item, provider, account_id: accountId, account_alias: `${provider}-alias` }]} sort="name" onSort={vi.fn()} /></MemoryRouter>);
  const headers = screen.getAllByRole('columnheader').map(cell => cell.textContent);
  const cells = screen.getAllByRole('row')[1].querySelectorAll('td');
  expect(cells[headers.indexOf('Account')]).toHaveTextContent('Demo');
  expect(cells[headers.indexOf('Account')]).not.toHaveTextContent(accountId);
  expect(cells[headers.indexOf('Account alias')]).toHaveTextContent(`${provider}-alias`);
  expect(cells[headers.indexOf('Account ID')]).toHaveTextContent(accountId);
  fireEvent.click(screen.getByRole('button', { name: `Copy account ID ${accountId}` }));
  await screen.findByText('Account ID copied.');
  expect(copy).toHaveBeenCalledExactlyOnceWith(accountId);
  expect(navigate).not.toHaveBeenCalled();
});

test('null account alias is explicit and account ID copy failure stays inline', async () => {
  vi.stubGlobal('navigator', { clipboard: { writeText: vi.fn().mockRejectedValue(new Error('Denied')) } });
  render(<MemoryRouter><InstanceTable items={[{ ...item, account_alias: null }]} sort="name" onSort={vi.fn()} /></MemoryRouter>);
  expect(screen.getByText('–')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: `Copy account ID ${item.account_id}` }));
  await screen.findByText('Unable to copy. Select and copy the account ID.');
  expect(navigate).not.toHaveBeenCalled();
});

test('copies the name and each private and public IP', async () => {
  const copy = vi.fn().mockResolvedValue(undefined);
  vi.stubGlobal('navigator', { clipboard: { writeText: copy } });
  render(<MemoryRouter><InstanceTable items={[{ ...item, private_ips: ['10.0.0.1', '10.0.0.2'], public_ips: ['203.0.113.10'] }]} sort="name" onSort={vi.fn()} /></MemoryRouter>);
  fireEvent.click(screen.getByRole('button', { name: 'Copy name web-1' }));
  await screen.findByText('Name copied.');
  fireEvent.click(screen.getByRole('button', { name: 'Copy private IP 10.0.0.2' }));
  await screen.findByText('Private IP copied.');
  fireEvent.click(screen.getByRole('button', { name: 'Copy public IP 203.0.113.10' }));
  await screen.findByText('Public IP copied.');
  expect(copy.mock.calls).toEqual([['web-1'], ['10.0.0.2'], ['203.0.113.10']]);
  expect(navigate).not.toHaveBeenCalled();
});

test('unnamed instances and empty IP lists have no copy button', () => {
  render(<MemoryRouter><InstanceTable items={[{ ...item, name: '' }]} sort="name" onSort={vi.fn()} /></MemoryRouter>);
  expect(screen.queryByRole('button', { name: /^Copy name/ })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /IP/ })).not.toBeInTheDocument();
});
