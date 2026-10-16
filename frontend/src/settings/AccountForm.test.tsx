import { fireEvent, screen, waitFor } from '@testing-library/react';
import { expect, test, vi } from 'vitest';
import { ApiError } from '../api/client';
import type { AccountSummary } from '../api/types';
import { fetchApi, renderSettings, response } from '../test/settings';
import AccountForm from './AccountForm';

function fill() {
  fireEvent.change(screen.getByLabelText('Account ID'), { target: { value: '111111111111' } });
  fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Test' } });
}
test('creates a validated account with explicit defaults and selected regions', async () => {
  fetchApi.mockResolvedValue(response({}));
  const saved = vi.fn(); renderSettings(<AccountForm onSaved={saved} onCancel={vi.fn()} />);
  fill();
  fireEvent.change(screen.getByLabelText('Regions'), { target: { value: 'eu-central-1, us-east-1' } });
  fireEvent.click(screen.getByRole('button', { name: 'Add account' }));
  await waitFor(() => expect(saved).toHaveBeenCalledOnce());
  expect(fetchApi).toHaveBeenCalledWith('/api/accounts', expect.objectContaining({ method: 'POST', body: JSON.stringify({ provider: 'aws', account_id: '111111111111', name: 'Test', regions: ['eu-central-1', 'us-east-1'], excluded_regions: [], role_arn: null, external_id: null, enabled: true, connection_mode: 'runtime' }) }));
});
test.each([422, 409])('shows server %s beside its field, preserving the form', async status => {
  const detail = status === 422 ? [{ loc: ['body', 'role_arn'], msg: 'Role is invalid', type: 'value_error' }] : 'Account already exists';
  fetchApi.mockRejectedValue(new ApiError(status, detail));
  renderSettings(<AccountForm onSaved={vi.fn()} onCancel={vi.fn()} />);
  fill();
  if (status === 422) {
    fireEvent.change(screen.getByLabelText('Connection method'), { target: { value: 'role' } });
    fireEvent.change(screen.getByLabelText('Role ARN'), { target: { value: 'arn:aws:iam::111111111111:role/test' } });
  }
  fireEvent.click(screen.getByRole('button', { name: 'Add account' }));
  const alert = await screen.findByRole('alert');
  expect(alert).toHaveTextContent(status === 422 ? 'Role is invalid' : 'Account already exists');
  const field = screen.getByRole('textbox', { name: status === 422 ? /^Role ARN/ : /^Account ID/ });
  expect(field).toHaveAttribute('aria-invalid', 'true');
  expect(field).toHaveAttribute('aria-describedby', alert.id);
  expect(screen.getByLabelText('Name')).toHaveValue('Test');
});
test('edits UI fields, clearing optional values without sending immutable or response fields', async () => {
  const account: AccountSummary = { provider: 'aws', account_id: '111111111111', name: 'Test', regions: 'all', role_arn: 'arn:aws:iam::111111111111:role/test', external_id: 'test-id', enabled: true, source: 'ui', cloud_alias: 'demo-alias', last_success_at: null, instance_count: 2 };
  fetchApi.mockResolvedValue(response({}));
  const saved = vi.fn(); renderSettings(<AccountForm account={account} onSaved={saved} onCancel={vi.fn()} />);
  expect(screen.getByLabelText('Provider')).toBeDisabled();
  expect(screen.getByLabelText('Account ID')).toHaveAttribute('readonly');
  expect(screen.queryByLabelText('Enabled')).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Renamed' } });
  for (const field of ['Role ARN', 'External ID (optional)']) fireEvent.change(screen.getByLabelText(field), { target: { value: '' } });
  fireEvent.change(screen.getByLabelText('Connection method'), { target: { value: 'runtime' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save account' }));
  await waitFor(() => expect(saved).toHaveBeenCalledOnce());
  expect(fetchApi).toHaveBeenCalledWith('/api/accounts/aws/111111111111', expect.objectContaining({ method: 'PATCH', body: '{"name":"Renamed","regions":"all","excluded_regions":[],"role_arn":null,"external_id":null,"connection_mode":"runtime"}' }));
});
test('rejects invalid input locally and supports Alibaba IDs without external ID', async () => {
  fetchApi.mockResolvedValue(response({}));
  const saved = vi.fn(); renderSettings(<AccountForm onSaved={saved} onCancel={vi.fn()} />);
  fill(); fireEvent.change(screen.getByLabelText('Provider'), { target: { value: 'alibaba' } });
  expect(screen.queryByLabelText('External ID (optional)')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Add account' }));
  expect(screen.getByRole('alert')).toHaveTextContent('16 digits');
  expect(fetchApi).not.toHaveBeenCalled();
  fireEvent.change(screen.getByRole('textbox', { name: /^Account ID/ }), { target: { value: '1111111111111111' } });
  fireEvent.click(screen.getByRole('button', { name: 'Add account' }));
  await waitFor(() => expect(saved).toHaveBeenCalledOnce());
});

test('trims the all-region sentinel before building the API payload', async () => {
  fetchApi.mockResolvedValue(response({}));
  const saved = vi.fn(); renderSettings(<AccountForm onSaved={saved} onCancel={vi.fn()} />);
  fill();
  fireEvent.change(screen.getByLabelText('Regions'), { target: { value: ' all ' } });
  fireEvent.click(screen.getByRole('button', { name: 'Add account' }));
  await waitFor(() => expect(saved).toHaveBeenCalledOnce());
  expect(JSON.parse(String(fetchApi.mock.calls[0][1]?.body)).regions).toBe('all');
});

test('tests unsaved settings and saves region checklist exclusions', async () => {
  fetchApi.mockImplementation(async path => response(path.endsWith('/test-connection') ? { ok: true, regions: ['us-east-1', 'us-west-2'] } : {}));
  const saved = vi.fn();
  renderSettings(<AccountForm onSaved={saved} onCancel={vi.fn()} />);
  fill(); fireEvent.click(screen.getByRole('button', { name: 'Test connection' }));
  expect(await screen.findByText('Connection OK. Select regions to exclude.')).toBeInTheDocument();
  expect(saved).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('checkbox', { name: 'us-west-2' }));
  fireEvent.click(screen.getByRole('button', { name: 'Add account' }));
  await waitFor(() => expect(saved).toHaveBeenCalledOnce());
  expect(JSON.parse(String(fetchApi.mock.calls.find(([path]) => path === '/api/accounts')?.[1]?.body)).excluded_regions).toEqual(['us-west-2']);
});

test('pre-save dedicated test clears key inputs without putting keys in caches', async () => {
  fetchApi.mockResolvedValue(response({ ok: true, regions: ['us-east-1'] }));
  const client = renderSettings(<AccountForm dedicatedEnabled onSaved={vi.fn()} onCancel={vi.fn()} />);
  fill();
  fireEvent.change(screen.getByLabelText('Access Key ID'), { target: { value: 'fixture-key' } });
  fireEvent.change(screen.getByLabelText('Secret Access Key'), { target: { value: 'fixture-secret' } });
  fireEvent.click(screen.getByRole('button', { name: 'Test connection' }));
  await screen.findByText('Connection OK. Select regions to exclude.');
  expect(screen.getByLabelText('Access Key ID')).toHaveValue('');
  expect(screen.getByLabelText('Secret Access Key')).toHaveValue('');
  expect(fetchApi.mock.calls).toHaveLength(1);
  expect(fetchApi.mock.calls[0][0]).toBe('/api/accounts/test-connection');
  expect(JSON.parse(String(fetchApi.mock.calls[0][1]?.body)).credentials.secret_access_key).toBe('fixture-secret');
  expect(JSON.stringify(client.getMutationCache().getAll().map(item => item.state))).not.toContain('fixture-');
  expect(JSON.stringify(client.getQueryCache().getAll().map(item => item.state))).not.toContain('fixture-');
});

test('failed pre-save check displays sanitized error and does not save', async () => {
  fetchApi.mockResolvedValue(response({ ok: false, error: 'Region discovery failed: AccessDenied' }));
  const saved = vi.fn(); renderSettings(<AccountForm onSaved={saved} onCancel={vi.fn()} />);
  fill(); fireEvent.click(screen.getByRole('button', { name: 'Test connection' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('AccessDenied');
  expect(saved).not.toHaveBeenCalled();
});


test('retyping dedicated keys retains the discovered checklist and selected exclusions', async () => {
  fetchApi.mockResolvedValue(response({ ok: true, regions: ['us-east-1', 'us-west-2'] }));
  renderSettings(<AccountForm dedicatedEnabled onSaved={vi.fn()} onCancel={vi.fn()} />);
  fill();
  fireEvent.change(screen.getByLabelText('Access Key ID'), { target: { value: 'fixture-key' } });
  fireEvent.change(screen.getByLabelText('Secret Access Key'), { target: { value: 'fixture-secret' } });
  fireEvent.click(screen.getByRole('button', { name: 'Test connection' }));
  await screen.findByRole('checkbox', { name: 'us-west-2' });
  for (const label of ['Access Key ID', 'Secret Access Key', 'Session Token (optional)']) {
    fireEvent.change(screen.getByLabelText(label), { target: { value: 'fixture-retyped' } });
    expect(screen.getByRole('checkbox', { name: 'us-west-2' })).toBeInTheDocument();
  }
  fireEvent.click(screen.getByRole('checkbox', { name: 'us-west-2' }));
  expect(screen.getByRole('checkbox', { name: 'us-west-2' })).toBeChecked();
  expect(screen.getByText('Connection OK. Select regions to exclude.')).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Regions'), { target: { value: 'us-east-1' } });
  expect(screen.queryByText('Connection OK. Select regions to exclude.')).not.toBeInTheDocument();
  expect(screen.queryByRole('checkbox', { name: 'us-east-1' })).not.toBeInTheDocument();
});
