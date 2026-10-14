import { fireEvent, screen, waitFor } from '@testing-library/react';
import { expect, test, vi } from 'vitest';
import { ApiError } from '../api/client';
import { fetchApi, renderSettings, response } from '../test/settings';
import AccountForm from './AccountForm';
import CloudAccounts from './CloudAccounts';

test.each(['aws', 'alibaba'])('submits write-only %s keys once and clears inputs and mutation variables', async provider => {
  fetchApi.mockRejectedValue(new ApiError(422, 'Account identity mismatch'));
  const client = renderSettings(<AccountForm dedicatedEnabled onSaved={vi.fn()} onCancel={vi.fn()} />);
  fireEvent.change(screen.getByLabelText('Provider'), { target: { value: provider } });
  fireEvent.change(screen.getByLabelText('Account ID'), { target: { value: provider === 'aws' ? '111111111111' : '1111111111111111' } });
  fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Demo' } });
  fireEvent.change(screen.getByLabelText('Connection method'), { target: { value: 'dedicated' } });
  const id = screen.getByLabelText('Access Key ID'); const secret = screen.getByLabelText(provider === 'aws' ? 'Secret Access Key' : 'Access Key Secret');
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
