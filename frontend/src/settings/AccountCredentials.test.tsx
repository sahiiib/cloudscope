import { fireEvent, screen, waitFor } from '@testing-library/react';
import { expect, test, vi } from 'vitest';
import { ApiError } from '../api/client';
import { fetchApi, renderSettings, response } from '../test/settings';
import AccountForm from './AccountForm';
import CloudAccounts from './CloudAccounts';

test.each(['aws', 'alibaba'])('new %s account opens with the requested key fields', provider => {
  renderSettings(<AccountForm dedicatedEnabled onSaved={vi.fn()} onCancel={vi.fn()} />);
  fireEvent.change(screen.getByLabelText('Provider'), { target: { value: provider } });
  expect(screen.getByLabelText('Connection method')).toHaveValue('dedicated');
  expect(screen.getByLabelText('Access Key ID')).toBeInTheDocument();
  expect(screen.getByLabelText('Secret Access Key')).toBeInTheDocument();
});

test('delete cancellation retains the account; confirmed deletion removes it and refreshes inventory', async () => {
  const row = { provider: 'aws', account_id: '111111111111', name: 'Delete demo', source: 'file', regions: 'all', configuration_version: 4, enabled: true, instance_count: 3 };
  let removed = false;
  fetchApi.mockImplementation(async (path, options) => {
    if (path.endsWith('/capabilities')) return response({ dedicated_credentials: true });
    if (options?.method === 'DELETE') { removed = true; return response({}); }
    return response(removed ? [] : [row]);
  });
  const client = renderSettings(<CloudAccounts />);
  const invalidate = vi.spyOn(client, 'invalidateQueries');
  fireEvent.click(await screen.findByRole('button', { name: 'Delete Delete demo' }));
  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
  expect(removed).toBe(false);
  fireEvent.click(screen.getByRole('button', { name: 'Delete Delete demo' }));
  fireEvent.click(screen.getByRole('button', { name: 'Delete account' }));
  await screen.findByText('No cloud accounts yet.');
  expect(fetchApi).toHaveBeenCalledWith('/api/accounts/aws/111111111111', expect.objectContaining({ method: 'DELETE', body: '{"confirmed":true,"expected_version":4}' }));
  for (const key of ['accounts', 'instances', 'load-balancers', 'sync']) expect(invalidate).toHaveBeenCalledWith({ queryKey: [key] });
});

test.each(['aws', 'alibaba'])('submits write-only %s keys once and clears inputs and mutation variables', async provider => {
  fetchApi.mockRejectedValue(new ApiError(422, 'Account identity mismatch'));
  const client = renderSettings(<AccountForm dedicatedEnabled onSaved={vi.fn()} onCancel={vi.fn()} />);
  fireEvent.change(screen.getByLabelText('Provider'), { target: { value: provider } });
  fireEvent.change(screen.getByLabelText('Account ID'), { target: { value: provider === 'aws' ? '111111111111' : '1111111111111111' } });
  fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Demo' } });
  fireEvent.change(screen.getByLabelText('Connection method'), { target: { value: 'dedicated' } });
  const id = screen.getByLabelText('Access Key ID'); const secret = screen.getByLabelText('Secret Access Key');
  expect(id).toHaveAttribute('type', 'password'); expect(secret).toHaveAttribute('type', 'password');
  if (provider === 'alibaba') expect(screen.queryByLabelText('Session Token (optional)')).not.toBeInTheDocument();
  fireEvent.change(id, { target: { value: 'fixture-key' } }); fireEvent.change(secret, { target: { value: 'fixture-secret' } });
  fireEvent.click(screen.getByRole('button', { name: 'Add account' }));
  await screen.findByRole('alert');
  expect(id).toHaveValue(''); expect(secret).toHaveValue('');
  const payload = JSON.parse(String(fetchApi.mock.calls[0][1]?.body));
  expect(payload.credentials).toEqual({ access_key_id: 'fixture-key', secret_access_key: 'fixture-secret' });
  expect(payload.connection_mode).toBe('dedicated');
  expect(JSON.stringify(client.getMutationCache().getAll().map(m => m.state.variables))).not.toContain('fixture-');
  expect(JSON.stringify(client.getQueryCache().getAll().map(q => q.state.data))).not.toContain('fixture-');
});

test('provider change removes old keys and cancellation cannot submit', () => {
  renderSettings(<AccountForm dedicatedEnabled onSaved={vi.fn()} onCancel={vi.fn()} />);
  fireEvent.change(screen.getByLabelText('Connection method'), { target: { value: 'dedicated' } });
  fireEvent.change(screen.getByLabelText('Access Key ID'), { target: { value: 'fixture-key' } });
  fireEvent.change(screen.getByLabelText('Provider'), { target: { value: 'alibaba' } });
  expect(screen.getByLabelText('Access Key ID')).toHaveValue('');
  fireEvent.click(screen.getByRole('button', { name: 'Cancel' })); expect(fetchApi).not.toHaveBeenCalled();
});

test('adoption needs explicit confirmation and retains the existing account identity', async () => {
  const old = { provider: 'aws', account_id: '111111111111', name: 'Old account', regions: 'all', role_arn: null, external_id: null, enabled: false, source: 'file', cloud_alias: 'alias', last_success_at: null, instance_count: 3, configuration_version: 1 };
  let adopted = false;
  fetchApi.mockImplementation(async (path) => {
    if (path.endsWith('/capabilities')) return response({ dedicated_credentials: true });
    if (path.endsWith('/adopt')) { adopted = true; return response({ ...old, source: 'ui' }); }
    return response([{ ...old, source: adopted ? 'ui' : 'file' }]);
  });
  renderSettings(<CloudAccounts />);
  fireEvent.click(await screen.findByRole('button', { name: 'Manage Old account in web' }));
  expect(screen.getByText(/Web settings will take precedence/)).toBeInTheDocument();
  expect(adopted).toBe(false);
  fireEvent.click(screen.getByRole('button', { name: 'Confirm web management' }));
  await waitFor(() => expect(screen.getByRole('button', { name: 'Edit Old account' })).toBeEnabled());
  expect(fetchApi).toHaveBeenCalledWith('/api/accounts/aws/111111111111/adopt', expect.objectContaining({ body: '{"confirmed":true,"expected_version":1}' }));
  expect(screen.getByText('111111111111')).toBeInTheDocument();
});
