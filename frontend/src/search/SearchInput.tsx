import { useEffect, useRef, useState } from 'react';

export default function SearchInput({ value, revision, onChange, label = 'Search instances', placeholder = 'Instance or account name, alias, ID, IP or tag…' }: { value: string; revision: string; onChange: (value: string) => void; label?: string; placeholder?: string }) {
  const [draft, setDraft] = useState(value);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const [previousRevision, setPreviousRevision] = useState(revision);
  if (previousRevision !== revision) {
    setPreviousRevision(revision);
    setDraft(value);
  }
  useEffect(() => { clearTimeout(timer.current); }, [revision]);
  useEffect(() => () => clearTimeout(timer.current), []);
  return <label>{label}
    <input type="search" value={draft} placeholder={placeholder} onChange={(event) => {
      const next = event.target.value;
      setDraft(next);
      clearTimeout(timer.current);
      timer.current = setTimeout(() => onChange(next), 300);
    }} />
  </label>;
}
