import { useEffect, useRef, useState } from 'react';
import type { AccountSummary } from '../api/types';
import AccountForm from './AccountForm';

export default function AccountDialog({ account, dedicatedEnabled, onSaved, onClose }: {
  account?: AccountSummary; dedicatedEnabled: boolean; onSaved: () => void; onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [dirty, setDirty] = useState(false);
  const [discard, setDiscard] = useState(false);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    const element = dialog.current;
    element?.showModal();
    return () => { queueMicrotask(() => { if (!element?.isConnected) opener?.focus(); }); };
  }, []);
  function close() { if (!busy) { if (dirty) setDiscard(true); else onClose(); } }
  return <dialog ref={dialog} className="account-dialog" aria-label={account ? `Edit ${account.name}` : 'Add cloud account'} onCancel={event => { event.preventDefault(); close(); }} onKeyDown={event => {
    if (event.key !== 'Tab') return;
    const focusable = Array.from(event.currentTarget.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), select:not(:disabled), [tabindex="0"]')).filter(element => !element.closest('fieldset:disabled'));
    const first = focusable[0], last = focusable.at(-1);
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
  }}>
    <AccountForm account={account} dedicatedEnabled={dedicatedEnabled} onSaved={onSaved} onCancel={close} onDirty={() => setDirty(true)} onBusy={setBusy} />
    {discard && <div className="settings-confirm" role="group" aria-label="Discard unsaved changes"><p>Discard unsaved changes?</p><button type="button" onClick={onClose}>Discard changes</button><button type="button" onClick={() => setDiscard(false)}>Keep editing</button></div>}
  </dialog>;
}
