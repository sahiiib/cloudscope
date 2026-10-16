import { fireEvent, render, screen } from '@testing-library/react';
import { expect, test } from 'vitest';
import FloatingScroll from './FloatingScroll';

test('the floating bar and the table scroll together', () => {
  const { container } = render(<FloatingScroll className="demo-scroll"><table><tbody><tr><td>wide</td></tr></tbody></table></FloatingScroll>);
  const content = container.querySelector('.demo-scroll') as HTMLDivElement;
  const bar = container.querySelector('.floating-scroll-bar') as HTMLDivElement;
  expect(screen.getByText('wide')).toBeInTheDocument();
  bar.scrollLeft = 120; fireEvent.scroll(bar);
  expect(content.scrollLeft).toBe(120);
  content.scrollLeft = 40; fireEvent.scroll(content);
  expect(bar.scrollLeft).toBe(40);
});
