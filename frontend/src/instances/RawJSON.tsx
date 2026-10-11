import { useState } from 'react';

export default function RawJSON({ raw }: { raw: Record<string, unknown> | null }) {
  const [status, setStatus] = useState('');
  const text = raw && Object.keys(raw).length ? JSON.stringify(raw, null, 2) : null;
  return <section aria-labelledby="instance-raw"><h2 id="instance-raw">Raw JSON</h2>
    {!text ? <p>Not available</p> : <details><summary>Show provider payload</summary>
      <button className="secondary" onClick={async () => {
        try { await navigator.clipboard.writeText(text); setStatus('JSON copied.'); }
        catch { setStatus('Unable to copy. Select and copy the JSON below.'); }
      }}>Copy JSON</button><p role="status">{status}</p><pre>{text}</pre>
    </details>}
  </section>;
}
