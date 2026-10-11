import { render, screen } from '@testing-library/react';
import { expect, test } from 'vitest';
import Tags from './Tags';

test('shows every tag, including literal markup and empty values', () => {
  render(<Tags tags={{ a: '1', b: '2', c: '3', d: '<script>example</script>', empty: '' }} />);
  expect(screen.getAllByRole('row')).toHaveLength(6);
  expect(screen.getByText('<script>example</script>')).toBeInTheDocument();
  expect(document.querySelector('script')).toBeNull();
});
test.each([{}, null])('missing tags are explicit', tags => {
  render(<Tags tags={tags} />); expect(screen.getByText('Not available')).toBeInTheDocument();
});
