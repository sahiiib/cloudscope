import { useEffect, useRef, useState } from 'react';

export default function SearchInput({ value, revision, onChange }: { value: string; revision: string; onChange: (value: string) => void }) {
  const [draft, setDraft] = useState(value);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const [previousRevision, setPreviousRevision] = useState(revision);
  if (previousRevision !== revision) {
    setPreviousRevision(revision);
    setDraft(value);
  }
  useEffect(() => { clearTimeout(timer.current); }, [revision]);
  useEffect(() => () => clearTimeout(timer.current), []);
  return <label>Search instances
    <input type="search" value={draft} placeholder="Name, instance ID, IP or tag…" onChange={(event) => {
      const next = event.target.value;
      setDraft(next);
      clearTimeout(timer.current);
      timer.current = setTimeout(() => onChange(next), 300);
    }} />
  </label>;
}
