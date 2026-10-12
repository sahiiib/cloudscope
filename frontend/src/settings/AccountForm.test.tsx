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
  expect(fetchApi).toHaveBeenCalledWith('/api/accounts', expect.objectContaining({ method: 'POST', body: JSON.stringify({ provider: 'aws', account_id: '111111111111', name: 'Test', regions: ['eu-central-1', 'us-east-1'], role_arn: null, external_id: null, enabled: true }) }));
});
test.each([422, 409])('shows server %s beside its field, preserving the form', async status => {
  const detail = status === 422 ? [{ loc: ['body', 'role_arn'], msg: 'Role is invalid', type: 'value_error' }] : 'Account already exists';
  fetchApi.mockRejectedValue(new ApiError(status, detail));
  renderSettings(<AccountForm onSaved={vi.fn()} onCancel={vi.fn()} />);
  fill(); fireEvent.click(screen.getByRole('button', { name: 'Add account' }));
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
  for (const field of ['Role ARN (optional)', 'External ID (optional)']) fireEvent.change(screen.getByLabelText(field), { target: { value: '' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save account' }));
  await waitFor(() => expect(saved).toHaveBeenCalledOnce());
  expect(fetchApi).toHaveBeenCalledWith('/api/accounts/aws/111111111111', expect.objectContaining({ method: 'PATCH', body: '{"name":"Renamed","regions":"all","role_arn":null,"external_id":null}' }));
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
