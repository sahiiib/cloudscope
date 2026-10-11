import { useState } from 'react';
import { fireEvent, screen, waitFor } from '@testing-library/react';
import { expect, test, vi } from 'vitest';
import { ApiError } from '../api/client';
import { fetchApi, renderSettings, response } from '../test/settings';
import MFASettings from './MFASettings';

function Enrollment() {
  const [enabled, setEnabled] = useState(false);
  return <MFASettings enabled={enabled} onChanged={setEnabled} />;
}
const provisioning = { otpauth_uri: 'otpauth://totp/example?secret=TESTONLY', qr_svg: '<svg xmlns="http://www.w3.org/2000/svg"></svg>' };
test('enrolls with a local QR, confirms a code and removes provisioning data', async () => {
  fetchApi.mockImplementation(async path => path.endsWith('/setup') ? response(provisioning) : new Response(null, { status: 204 }));
  const client = renderSettings(<Enrollment />);
  fireEvent.click(screen.getByRole('button', { name: 'Set up MFA' }));
  const qr = await screen.findByRole('img', { name: 'Authenticator enrollment QR code' });
  expect(qr).toHaveAttribute('src', `data:image/svg+xml;charset=utf-8,${encodeURIComponent(provisioning.qr_svg)}`);
  expect(client.getMutationCache().getAll().every(mutation => mutation.state.data === undefined)).toBe(true);
  fireEvent.change(screen.getByLabelText('Authenticator code'), { target: { value: '123456' } });
  fireEvent.submit(screen.getByRole('form', { name: 'Confirm MFA' }));
  expect(await screen.findByRole('button', { name: 'Disable MFA' })).toBeInTheDocument();
  expect(fetchApi).toHaveBeenCalledWith('/api/auth/mfa/enable', expect.objectContaining({ body: '{"code":"123456"}', redirectOnUnauthorized: false }));
  expect(screen.queryByRole('img')).not.toBeInTheDocument();
  expect(screen.queryByText(provisioning.otpauth_uri)).not.toBeInTheDocument();
});
test('disabling requires password/code and keeps invalid-code errors inline', async () => {
  fetchApi.mockRejectedValueOnce(new ApiError(401)).mockResolvedValue(new Response(null, { status: 204 }));
  const changed = vi.fn(); renderSettings(<MFASettings enabled onChanged={changed} />);
  for (let attempt = 0; attempt < 2; attempt++) {
    fireEvent.change(screen.getByLabelText('MFA password'), { target: { value: 'password-placeholder' } });
    fireEvent.change(screen.getByLabelText('Authenticator code'), { target: { value: attempt ? '234567' : '123456' } });
    fireEvent.submit(screen.getByRole('form', { name: 'Disable MFA' }));
    if (!attempt) {
      expect(await screen.findByRole('alert')).toHaveTextContent('fresh code');
      expect(screen.getByLabelText('MFA password')).toHaveValue('');
      expect(screen.getByLabelText('Authenticator code')).toHaveValue('');
      expect(changed).not.toHaveBeenCalled();
    }
  }
  await waitFor(() => expect(changed).toHaveBeenCalledWith(false));
  expect(fetchApi).toHaveBeenLastCalledWith('/api/auth/mfa/disable', expect.objectContaining({ body: '{"password":"password-placeholder","code":"234567"}' }));
});
test('cancel removes the QR and the next setup requests new provisioning data', async () => {
  fetchApi.mockImplementation(async () => response(provisioning)); renderSettings(<Enrollment />);
  fireEvent.click(screen.getByRole('button', { name: 'Set up MFA' })); await screen.findByRole('img');
  fireEvent.click(screen.getByRole('button', { name: 'Cancel setup' }));
  expect(screen.queryByRole('img')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Set up MFA' })); await screen.findByRole('img');
  expect(fetchApi).toHaveBeenCalledTimes(2);
});
