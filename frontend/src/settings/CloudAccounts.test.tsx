import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { expect, test, vi } from 'vitest';
import { ApiError } from '../api/client';
import type { AccountSummary } from '../api/types';
import { fetchApi, renderSettings, response } from '../test/settings';
import CloudAccounts from './CloudAccounts';

const account: AccountSummary = { provider: 'aws', account_id: '111111111111', name: 'UI test', regions: 'all', role_arn: null, external_id: null, enabled: true, source: 'ui', cloud_alias: 'demo-alias', last_success_at: null, instance_count: 3 };
const refreshKeys = ['accounts', 'instance-facets', 'instances', 'instance', 'sync'];

test('file rows expose their configuration without edit or status controls', async () => {
  fetchApi.mockResolvedValue(response([{ ...account, source: 'file', regions: ['eu-central-1'], role_arn: 'arn:aws:iam::111111111111:role/test', last_success_at: '2026-01-01T00:00:00Z' }]));
  renderSettings(<CloudAccounts />);
  const row = (await screen.findByText('Managed by accounts.yaml')).closest('tr')!;
  for (const text of ['AWS', 'UI test', '111111111111', 'eu-central-1', 'Enabled', '3']) expect(within(row).getByText(text)).toBeInTheDocument();
  expect(row.querySelector('time')).toHaveAttribute('datetime', '2026-01-01T00:00:00Z');
  expect(within(row).queryByRole('button', { name: /^Edit|^Disable|^Enable/ })).not.toBeInTheDocument();
  expect(within(row).getByRole('button', { name: 'Test access for UI test' })).toBeInTheDocument();
});

test('enable/disable needs confirmation; cancellation does not mutate; all relevant caches invalidate', async () => {
  let current = { ...account };
  fetchApi.mockImplementation(async (_path, options) => {
    if (options?.method === 'PATCH') current = { ...current, ...JSON.parse(String(options.body)) };
    return response([current]);
  });
  const client = renderSettings(<CloudAccounts />);
  const invalidate = vi.spyOn(client, 'invalidateQueries');
  fireEvent.click(await screen.findByRole('button', { name: 'Disable UI test' }));
  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
  expect(fetchApi.mock.calls.some(([, options]) => options?.method === 'PATCH')).toBe(false);
  for (const action of ['Disable', 'Enable']) {
    fireEvent.click(screen.getByRole('button', { name: `${action} UI test` }));
    fireEvent.click(screen.getByRole('button', { name: 'Confirm change' }));
    await waitFor(() => expect(screen.getByRole('button', { name: `${action === 'Disable' ? 'Enable' : 'Disable'} UI test` })).toBeEnabled());
    for (const key of refreshKeys) expect(invalidate).toHaveBeenCalledWith({ queryKey: [key] });
  }
  expect(fetchApi.mock.calls.filter(([, options]) => options?.method === 'PATCH').map(([, options]) => options?.body)).toEqual(['{"enabled":false}', '{"enabled":true}']);
});

test.each([true, false])('access test shows inline result for ok=%s', async ok => {
  fetchApi.mockImplementation(async path => response(path.endsWith('/test') ? ok ? { ok: true, regions: 12 } : { ok: false, error: 'Region discovery failed: AccessDenied' } : [account]));
  renderSettings(<CloudAccounts />);
  fireEvent.click(await screen.findByRole('button', { name: 'Test access for UI test' }));
  expect(await screen.findByText(ok ? 'Access OK · 12 regions' : 'Region discovery failed: AccessDenied')).toBeInTheDocument();
  expect(fetchApi).toHaveBeenCalledWith('/api/accounts/aws/111111111111/test', { method: 'POST' });
});

test('create and edit refresh account labels, facets and sync data', async () => {
  let rows: AccountSummary[] = [];
  fetchApi.mockImplementation(async (_path, options) => {
    if (options?.method === 'POST') rows = [{ ...account, name: 'Added' }];
    if (options?.method === 'PATCH') rows = [{ ...account, name: 'Renamed' }];
    return response(rows);
  });
  const client = renderSettings(<CloudAccounts />);
  const invalidate = vi.spyOn(client, 'invalidateQueries');
  await screen.findByText('No cloud accounts yet.');
  fireEvent.click(screen.getByRole('button', { name: 'Add cloud account' }));
  fireEvent.change(screen.getByLabelText('Account ID'), { target: { value: '111111111111' } });
  fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Added' } });
  fireEvent.click(screen.getByRole('button', { name: 'Add account' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Edit Added' }));
  for (const key of refreshKeys) expect(invalidate).toHaveBeenCalledWith({ queryKey: [key] });
  invalidate.mockClear();
  fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Renamed' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save account' }));
  await screen.findByRole('button', { name: 'Edit Renamed' });
  for (const key of refreshKeys) expect(invalidate).toHaveBeenCalledWith({ queryKey: [key] });
});

test('loading errors can retry and mutation permission failures stay inline', async () => {
  fetchApi.mockRejectedValueOnce(new ApiError(503));
  const client = renderSettings(<CloudAccounts />);
  await screen.findByRole('alert');
  fetchApi.mockImplementation(async (_path, options) => {
    if (options?.method) throw new ApiError(403);
    return response([account]);
  });
  fireEvent.click(screen.getByRole('button', { name: 'Retry accounts' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Disable UI test' }));
  fireEvent.click(screen.getByRole('button', { name: 'Confirm change' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('permission');
  expect(client.getQueryData(['accounts'])).toEqual([account]);
});

test.each(['demo-alias', null])('shows cloud alias %s in its own column', async cloud_alias => {
  fetchApi.mockResolvedValue(response([{ ...account, cloud_alias }]));
  renderSettings(<CloudAccounts />);
  const row = (await screen.findByText('UI test')).closest('tr')!;
  expect(screen.getByRole('columnheader', { name: 'Account alias' })).toBeInTheDocument();
  expect(within(row).getByText(cloud_alias ?? '–')).toBeInTheDocument();
  expect(within(row).getByText(account.account_id)).toBeInTheDocument();
});
