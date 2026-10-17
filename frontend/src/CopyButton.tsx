import { CopyIcon } from './icons';

// Icon-only copy button; the status line is owned by the page so one message is announced.
export default function CopyButton({ value, label, what, onStatus }: {
  value: string; label: string; what: string; onStatus: (message: string) => void;
}) {
  const noun = what.charAt(0).toLowerCase() + what.slice(1); // keeps acronyms: "instance ID"
  return <button type="button" className="secondary icon-button" aria-label={label} title={`Copy ${noun}`} onClick={async event => {
    event.stopPropagation();
    try { await navigator.clipboard.writeText(value); onStatus(`${what} copied.`); }
    catch { onStatus(`Unable to copy. Select and copy the ${noun}.`); }
  }}><CopyIcon /></button>;
}
