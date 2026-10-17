import type { Facet } from '../api/types';

export default function FacetFilter({ label, options, selected, names = {}, open, onToggle, onChange }: {
  label: string; options: Facet[]; selected: string[]; names?: Record<string, string>;
  open: boolean; onToggle: (open: boolean) => void;
  onChange: (value: string, checked: boolean) => void;
}) {
  const all = [...options, ...selected.filter(value => !options.some(item => item.value === value)).map(value => ({ value, count: 0 }))];
  // The parent owns which filter is open, so opening one closes the others.
  return <details className="facet" open={open}><summary onClick={event => { event.preventDefault(); onToggle(!open); }}>{label}{selected.length > 0 && ` (${selected.length})`}</summary>
    <fieldset><legend className="sr-only">{label}</legend>
      {all.length === 0 && <span>No options</span>}
      {all.map(({ value, count }) => <label key={value}>
        <input type="checkbox" checked={selected.includes(value)} onChange={event => onChange(value, event.target.checked)} />
        {names[value] ? `${names[value]} · ${value}` : value} <span>({count})</span>
      </label>)}
    </fieldset>
  </details>;
}
