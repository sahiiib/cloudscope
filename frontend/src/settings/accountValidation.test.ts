import { expect, test } from 'vitest';
import type { AccountInput } from '../api/types';
import { validateAccount } from './accountValidation';

const input: AccountInput = { provider: 'aws', account_id: '111111111111', name: 'Test', regions: 'all', role_arn: null, external_id: null, enabled: true };
test.each<[keyof AccountInput, unknown]>([
  ['provider', 'other'], ['account_id', '123'], ['account_id', '１２３４５６７８９０１２'], ['account_id', 'a'.repeat(12)],
  ['name', ''], ['name', ' test'], ['name', 'test '], ['name', 'bad\nname'], ['name', 'x'.repeat(65)],
  ['role_arn', 'arn:aws:iam::222222222222:role/test'], ['role_arn', 'acs:ram::111111111111:role/test'], ['role_arn', ''],
  ['external_id', 'a'], ['external_id', 'x'.repeat(1225)], ['external_id', 'bad value'], ['external_id', 'éé'],
  ['regions', []], ['regions', ['us-east-1', 'us-east-1']], ['regions', ['UpperCase']], ['regions', ['x']], ['regions', ['x'.repeat(33)]], ['regions', ['a_b']],
  ['enabled', 'true'], ['account_id', '111111111111\n'], ['role_arn', 'arn:aws:iam::111111111111:role/test\n'], ['external_id', 'test\n'], ['regions', ['us-east-1\n']],
])('rejects invalid %s', (field, value) => {
  expect(validateAccount({ ...input, [field]: value })[field]).toBeTruthy();
});
test('accepts both providers, boundary lengths and matching role paths', () => {
  expect(validateAccount({ ...input, name: '😀'.repeat(64), role_arn: 'arn:aws:iam::111111111111:role/path/test', external_id: 'x'.repeat(1224), regions: ['eu-central-1', 'us-east-1'] })).toEqual({});
  expect(validateAccount({ ...input, provider: 'alibaba', account_id: '1111111111111111', role_arn: 'acs:ram::1111111111111111:role/test' })).toEqual({});
  expect(validateAccount({ ...input, provider: 'alibaba', external_id: 'test' })).toHaveProperty('external_id');
});
