import { useEffect, useRef, useState, type ReactNode } from 'react';

// Wide tables scroll inside `className`; a copy of the horizontal scrollbar sticks to the
// bottom of the window so it can be used without scrolling to the end of a long table.
export default function FloatingScroll({ className, children }: { className: string; children: ReactNode }) {
  const content = useRef<HTMLDivElement>(null);
  const bar = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  const [overflowing, setOverflowing] = useState(false);
  useEffect(() => {
    const element = content.current;
    if (!element) return;
    const measure = () => { setWidth(element.scrollWidth); setOverflowing(element.scrollWidth > element.clientWidth + 1); };
    measure();
    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    if (element.firstElementChild) observer.observe(element.firstElementChild);
    return () => observer.disconnect();
  }, []);
  function sync(from: HTMLDivElement | null, to: HTMLDivElement | null) {
    if (from && to && to.scrollLeft !== from.scrollLeft) to.scrollLeft = from.scrollLeft;
  }
  return <div className="floating-scroll">
    <div ref={content} className={`${className} floating-scroll-content`} onScroll={() => sync(content.current, bar.current)}>{children}</div>
    <div ref={bar} className="floating-scroll-bar" hidden={!overflowing} aria-hidden="true" onScroll={() => sync(bar.current, content.current)}>
      <div style={{ width }} />
    </div>
  </div>;
}
